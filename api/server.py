import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import BaseMessage, HumanMessage

from fluxo_financeiro import app as langgraph_app

api = FastAPI(title="Pipeline Financeiro API")

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_executor = ThreadPoolExecutor(max_workers=4)

def _serialize_message(msg: BaseMessage) -> dict:
    content = msg.content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "\n".join(parts)
    return {
        "type": msg.__class__.__name__,
        "content": str(content),
        "name": getattr(msg, "name", None),
    }


@api.get("/analyze")
async def analyze_ticker(ticker: str):
    async def event_stream():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _run_graph():
            try:
                initial = {"messages": [HumanMessage(content=f"Analise a ação {ticker.upper()}")]}
                for event in langgraph_app.stream(initial):
                    for node_name, state_update in event.items():
                        payload: dict = {"node": node_name}
                        if "messages" in state_update:
                            payload["messages"] = [
                                _serialize_message(m) for m in state_update["messages"]
                            ]
                        if "next_agent" in state_update:
                            payload["next_agent"] = state_update["next_agent"]
                        if "loop_count" in state_update:
                            payload["loop_count"] = state_update["loop_count"]
                        if "supervisor_reasoning" in state_update:
                            payload["reasoning"] = state_update["supervisor_reasoning"]
                        if "decidido_por" in state_update:
                            payload["decidido_por"] = state_update["decidido_por"]
                        asyncio.run_coroutine_threadsafe(queue.put(payload), loop)
                asyncio.run_coroutine_threadsafe(queue.put({"done": True}), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(queue.put({"error": str(exc)}), loop)
                asyncio.run_coroutine_threadsafe(queue.put({"done": True}), loop)

        loop.run_in_executor(_executor, _run_graph)

        while True:
            item = await queue.get()
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if item.get("done") or item.get("error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
