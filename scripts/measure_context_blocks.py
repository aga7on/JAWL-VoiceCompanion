import asyncio
import os
import sys

sys.path.insert(0, "runtime/jawl-sources/jawl-20260906-daily-v2")
os.environ["JAWL_INSTANCE_ID"] = "daily"
os.environ["JAWL_PROFILE_NAME"] = "daily"
os.environ["JAWL_INSTANCE_HOME"] = os.path.abspath("runtime/instances/daily")

from src.utils.event.bus import EventBus
from src.utils.settings import load_config
from src.system.container import SystemContainer
from src.builder import SystemBuilder

async def main():
    settings, interfaces = load_config()
    event_bus = EventBus()
    container = SystemContainer(settings, interfaces, event_bus)
    builder = SystemBuilder(container)
    builder.with_l0_states()
    await builder.with_l1_databases()
    builder.with_l2_interfaces({"LLM_API_KEYS": ["dummy"]})
    builder.with_l3_agent({"LLM_API_KEYS": ["dummy"]})
    container = builder.build()
    
    context_builder = container.context_builder
    print(f"Context budget: max_dynamic_chars={context_builder.budget.max_dynamic_chars}, skills={context_builder.budget.skills_max_chars}, ticks={context_builder.budget.recent_ticks_max_chars}, provider={context_builder.budget.provider_max_chars}")
    
    print("\nMeasuring registered context providers:")
    blocks = {}
    for name, provider_info in context_builder.registry._providers.items():
        func = provider_info["func"]
        try:
            res = await func()
            blocks[name] = len(res)
            print(f"{name:30s}: {len(res):6d} chars")
        except Exception as e:
            print(f"{name:30s}: ERROR: {e}")
            
    total = sum(blocks.values())
    print("-" * 45)
    print(f"{'TOTAL RAW BLOCKS':30s}: {total:6d} chars")

if __name__ == "__main__":
    asyncio.run(main())
