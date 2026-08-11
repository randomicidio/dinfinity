# -*- coding: utf-8 -*-
"""Cliente OBS WebSocket (protocolo v5) usando apenas a biblioteca websockets.

Usado pelas reações "scripted" para trocar cenas, mostrar/esconder fontes,
ligar filtros, mutar áudio, etc. — substituindo o Streamer.bot.
"""
import asyncio
import base64
import hashlib
import json

import websockets

from core import logger

OP_HELLO = 0
OP_IDENTIFY = 1
OP_IDENTIFIED = 2
OP_REQUEST = 6
OP_RESPONSE = 7
OP_CLOSE = 8


class OBSClient:
    def __init__(self):
        self._ws = None
        self._next_id = 0
        self._pending = {}
        self._reader_task = None

    # ---------------- conexão ----------------
    @property
    def connected(self):
        return self._ws is not None

    async def connect(self, host="localhost", port=4455, password=""):
        uri = f"ws://{host}:{port}"
        try:
            ws = await websockets.connect(uri, open_timeout=5, close_timeout=5)
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
            if hello.get("op") != OP_HELLO:
                raise RuntimeError("OBS não enviou o handshake esperado.")
            identify = {"op": OP_IDENTIFY, "d": {"rpcVersion": 1, "eventSubscriptions": 0}}
            auth = (hello.get("d") or {}).get("authentication") or {}
            if password and auth:
                secret = base64.b64encode(
                    hashlib.sha256((password + auth.get("salt", "")).encode()).digest()
                ).decode()
                identify["d"]["authentication"] = base64.b64encode(
                    hashlib.sha256((secret + auth.get("challenge", "")).encode()).digest()
                ).decode()
            await ws.send(json.dumps(identify))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                if msg.get("op") == OP_IDENTIFIED:
                    break
                if msg.get("op") == OP_CLOSE:
                    raise RuntimeError("OBS fechou a conexão: " + str(msg.get("d")))
            self._ws = ws
            self._reader_task = asyncio.get_running_loop().create_task(self.run())
            logger.log("success", f"[OBS] Conectado em {uri}")
        except asyncio.TimeoutError:
            logger.log("error", f"[OBS] Timeout ao conectar em {uri} (OBS aberto e websocket ativo?)")
            raise
        except Exception as exc:
            logger.log("error", f"[OBS] Falha ao conectar em {uri}: {exc}")
            raise

    async def disconnect(self):
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    # ---------------- chamadas ----------------
    async def call(self, request_type, data=None, timeout=10):
        if self._ws is None:
            raise RuntimeError("OBS não está conectado.")
        self._next_id += 1
        rid = str(self._next_id)
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._ws.send(json.dumps({
                "op": OP_REQUEST,
                "d": {"requestType": request_type, "requestId": rid, "requestData": data or {}},
            }))
            resp = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)
        status = (resp.get("d") or {}).get("requestStatus") or {}
        if not status.get("result"):
            raise RuntimeError(f"[OBS] {request_type} falhou: {status.get('comment')}")
        return (resp.get("d") or {}).get("responseData") or {}

    async def _on_message(self, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        if msg.get("op") != OP_RESPONSE:
            return
        rid = (msg.get("d") or {}).get("requestId")
        fut = self._pending.get(rid)
        if fut is not None and not fut.done():
            fut.set_result(msg)

    async def run(self):
        """Consome mensagens enquanto conectado (loop de resposta)."""
        ws = self._ws
        try:
            async for raw in ws:
                await self._on_message(raw)
        except Exception:
            pass

    # ---------------- comandos de alto nível ----------------
    async def set_scene(self, scene_name):
        await self.call("SetCurrentProgramScene", {"sceneName": scene_name})

    async def get_scene_list(self):
        data = await self.call("GetSceneList")
        return data.get("scenes") or []

    # ---------------- listagens (alimentam os menus da GUI) ----------------
    async def listar_cenas(self):
        data = await self.call("GetSceneList")
        # O OBS devolve da última para a primeira; a ordem da tela é o inverso.
        nomes = [s.get("sceneName") for s in (data.get("scenes") or []) if s.get("sceneName")]
        return list(reversed(nomes))

    async def listar_fontes_da_cena(self, scene_name):
        if not scene_name:
            return []
        data = await self.call("GetSceneItemList", {"sceneName": scene_name})
        return [i.get("sourceName") for i in (data.get("sceneItems") or []) if i.get("sourceName")]

    async def listar_entradas(self):
        """Todas as entradas (câmeras, mídias, áudio...) do projeto."""
        data = await self.call("GetInputList")
        return [i.get("inputName") for i in (data.get("inputs") or []) if i.get("inputName")]

    async def listar_fontes(self):
        """Entradas + cenas: o filtro do OBS pode morar nos dois."""
        entradas = await self.listar_entradas()
        cenas = await self.listar_cenas()
        vistos, saida = set(), []
        for nome in entradas + cenas:
            if nome not in vistos:
                vistos.add(nome)
                saida.append(nome)
        return saida

    async def listar_filtros(self, source_name):
        if not source_name:
            return []
        data = await self.call("GetSourceFilterList", {"sourceName": source_name})
        return [f.get("filterName") for f in (data.get("filters") or []) if f.get("filterName")]

    async def _scene_item_id(self, scene_name, source_name):
        data = await self.call("GetSceneItemList", {"sceneName": scene_name})
        for item in data.get("sceneItems") or []:
            if item.get("sourceName") == source_name:
                return item.get("sceneItemId")
        raise RuntimeError(f"fonte '{source_name}' não encontrada na cena '{scene_name}'")

    async def set_source_visible(self, scene_name, source_name, visible):
        iid = await self._scene_item_id(scene_name, source_name)
        await self.call("SetSceneItemEnabled", {
            "sceneName": scene_name, "sceneItemId": iid,
            "sceneItemEnabled": bool(visible),
        })

    async def toggle_source(self, scene_name, source_name):
        iid = await self._scene_item_id(scene_name, source_name)
        resp = await self.call("GetSceneItemEnabled", {
            "sceneName": scene_name, "sceneItemId": iid,
        })
        await self.call("SetSceneItemEnabled", {
            "sceneName": scene_name, "sceneItemId": iid,
            "sceneItemEnabled": not bool(resp.get("sceneItemEnabled")),
        })

    async def set_filter(self, source_name, filter_name, enabled):
        await self.call("SetSourceFilterEnabled", {
            "sourceName": source_name, "filterName": filter_name,
            "filterEnabled": bool(enabled),
        })

    async def toggle_filter(self, source_name, filter_name):
        resp = await self.call("GetSourceFilter", {
            "sourceName": source_name, "filterName": filter_name,
        })
        await self.call("SetSourceFilterEnabled", {
            "sourceName": source_name, "filterName": filter_name,
            "filterEnabled": not bool(resp.get("filterEnabled")),
        })

    async def set_input_muted(self, input_name, muted):
        await self.call("SetInputMute", {
            "inputName": input_name, "inputMuted": bool(muted),
        })

    async def toggle_mute(self, input_name):
        resp = await self.call("GetInputMute", {"inputName": input_name})
        await self.call("SetInputMute", {
            "inputName": input_name,
            "inputMuted": not bool(resp.get("inputMuted")),
        })

    async def set_input_volume(self, input_name, volume):
        await self.call("SetInputVolume", {
            "inputName": input_name, "inputVolumeDb": float(volume),
        })

    async def start_stream(self):
        await self.call("StartStream")

    async def stop_stream(self):
        await self.call("StopStream")
