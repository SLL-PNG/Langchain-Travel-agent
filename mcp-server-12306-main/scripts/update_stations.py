import asyncio
import aiohttp
import aiofiles
import os
import sys
from datetime import datetime, timezone

# 兼容包路径，自动把项目根目录加入PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.mcp_12306.services.station_service import StationService

STATION_JS_URL = "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"
LOCAL_PATH = "src/mcp_12306/resources/station_name.js"

async def fetch_station_js(url=STATION_JS_URL, save_path=LOCAL_PATH):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"请求失败，状态码: {resp.status}")
            text = await resp.text(encoding='utf-8', errors='ignore')
            async with aiofiles.open(save_path, "w", encoding="utf-8") as f:
                await f.write(text)
    return save_path

async def update_stations():
    print("🚀 12306车站信息更新工具")
    print("=" * 50)
    print(f"🌐 数据源: {STATION_JS_URL}")
    print(f"⏰ 更新时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} (UTC)")
    print(f"👤 操作用户: {os.getenv('USERNAME') or os.getenv('USER') or 'unknown'}")
    print("=" * 50)
    try:
        print("📡 正在连接12306官网...")
        await fetch_station_js()
        print("✅ 已成功获取12306最新JS数据!")
    except Exception as e:
        print(f"❌ 获取失败: {e}")
        print("🔄 使用本地 station_name.js 文件继续解析...")
        if not os.path.exists(LOCAL_PATH):
            print("❌ 本地 station_name.js 文件不存在，无法继续。")
            sys.exit(1)
    print("🔍 正在解析车站数据...")
    service = StationService()
    await service.load_stations(path=LOCAL_PATH)
    print(f"✅ 共加载 {len(service.stations)} 个车站，示例：")
    for station in service.stations[:10]:
        print(f"    - {station.name}（{station.code}，{station.city}）")
    print("✨ 车站信息更新完成！")

if __name__ == "__main__":
    asyncio.run(update_stations())