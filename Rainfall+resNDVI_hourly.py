import os
import glob
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import netCDF4 as nc
from tqdm import tqdm
import concurrent.futures
import json
import warnings
from pathlib import Path
import threading

# 忽略警告
warnings.filterwarnings('ignore')

# 配置参数
RAIN_EVENTS_FILE = r"D:\H8_data\rain_events_all_stations.parquet"
NDVI_BASE_PATH = r"D:\H8_Data\H8NDVI"  # NDVI数据路径
OUTPUT_DIR = r"D:\H8_data\rain_ndvi_analysis"
PRE_RAIN_HOURS = 72  # 降雨前观察小时数
POST_RAIN_HOURS = 672  # 降雨后观察小时数 (28天)
TEMP_DATA_DIR = os.path.join(OUTPUT_DIR, "hourly_ndvi_data")  # 临时数据目录
MAX_WORKERS = 8  # 最大线程数

# 创建输出目录
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DATA_DIR, exist_ok=True)

# 状态文件路径
STATE_FILE = os.path.join(OUTPUT_DIR, "extraction_state.json")

# NDVI数据的小时范围
NDVI_HOURS = [*range(0, 13), 21, 22]

# 创建线程锁用于状态更新和文件访问
state_lock = threading.Lock()
file_access_lock = threading.Lock()  # 新增文件访问锁


def save_processing_state(start_date, end_date, processed_hours):
    """保存处理状态（线程安全）"""
    with state_lock:
        state = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "processed_hours": [h.isoformat() for h in processed_hours]
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)


def load_processing_state():
    """加载处理状态（线程安全）"""
    with state_lock:
        if not os.path.exists(STATE_FILE):
            return None, None, []

        with open(STATE_FILE, "r") as f:
            state = json.load(f)
            start_date = date.fromisoformat(state["start_date"])
            end_date = date.fromisoformat(state["end_date"])
            processed_hours = [datetime.fromisoformat(h) for h in state["processed_hours"]]
            return start_date, end_date, processed_hours


def clear_processing_state():
    """清除处理状态（线程安全）"""
    with state_lock:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)


def load_rain_events(start_date, end_date):
    """加载并过滤降雨事件数据（24小时全时段）"""
    print(f"加载降雨事件数据 ({start_date} 至 {end_date})...")
    rain_events = pd.read_parquet(RAIN_EVENTS_FILE)

    # 转换日期列为datetime类型
    rain_events['Start_Time'] = pd.to_datetime(rain_events['Start_Time'])
    rain_events['End_Time'] = pd.to_datetime(rain_events['End_Time'])

    # 过滤时间范围（只按日期过滤）
    mask = (rain_events['Start_Time'].dt.date >= start_date) & \
           (rain_events['Start_Time'].dt.date <= end_date)

    rain_events = rain_events[mask].copy()

    if rain_events.empty:
        print(f"警告: 在指定时间范围内未找到降雨事件!")
        return pd.DataFrame()

    # 添加降雨事件唯一ID
    rain_events['Event_ID'] = rain_events.groupby(['Station', 'Start_Time']).ngroup()

    # 计算四分位分组
    duration_quantiles = rain_events['Duration_hours'].quantile([0.25, 0.5, 0.75])
    rain_events['Duration_Group'] = pd.cut(
        rain_events['Duration_hours'],
        bins=[0, duration_quantiles[0.25], duration_quantiles[0.5],
              duration_quantiles[0.75], float('inf')],
        labels=['Q1', 'Q2', 'Q3', 'Q4']
    )

    print(f"找到 {len(rain_events)} 个符合时间范围的降雨事件")
    return rain_events


def find_ndvi_file_for_time(target_time):
    """根据时间查找对应的NDVI文件"""
    date_str = target_time.strftime("%Y%m%d")
    hour_str = target_time.strftime("%H00")
    pattern = os.path.join(NDVI_BASE_PATH, f"NDVI_{date_str}_{hour_str}.nc")
    files = glob.glob(pattern)
    return files[0] if files else None


def get_ndvi_for_station(ndvi_file, station_name):
    """从NDVI文件中获取指定站点的NDVI值（线程安全）"""
    try:
        # 使用文件访问锁保护NetCDF操作
        with file_access_lock:
            with nc.Dataset(ndvi_file) as ds:
                # 获取所有站点名称
                stations_var = ds.variables['Station'][:]

                # 处理不同格式的站点数据
                if stations_var.dtype.kind == 'S':  # 字节字符串
                    stations = [s.tobytes().decode('utf-8').strip() for s in stations_var]
                elif stations_var.dtype.kind == 'U':  # Unicode字符串
                    stations = [s.strip() for s in stations_var]
                else:  # 其他类型
                    stations = [str(s).strip() for s in stations_var]

                # 查找目标站点的索引
                station_idx = next((i for i, s in enumerate(stations) if s == station_name), None)

                if station_idx is None:
                    return np.nan

                # 获取NDVI值
                ndvi_values = ds.variables['NDVI'][:]
                return float(ndvi_values[station_idx])

    except Exception as e:
        print(f"读取NDVI文件 {ndvi_file} 时出错: {str(e)}")
        return np.nan


def extract_ndvi_for_event(event):
    """为单个降雨事件提取resNDVI时间窗口"""
    station = event['Station']
    start_time = event['Start_Time']
    end_time = event['End_Time']

    # 计算时间窗口
    pre_window_start = start_time - timedelta(hours=PRE_RAIN_HOURS)
    post_window_end = end_time + timedelta(hours=POST_RAIN_HOURS)

    # 创建时间序列（仅包含NDVI可用小时）
    time_points = []
    current_time = pre_window_start
    while current_time <= post_window_end:
        if current_time.hour in NDVI_HOURS:
            time_points.append(current_time)
        current_time += timedelta(hours=1)

    ndvi_data = []

    # 获取每个时间点的NDVI值
    for time_point in time_points:
        ndvi_file = find_ndvi_file_for_time(time_point)
        if not ndvi_file:
            ndvi_value = np.nan
        else:
            ndvi_value = get_ndvi_for_station(ndvi_file, station)

        # 创建数据记录
        record = {
            'Time': time_point,
            'NDVI': ndvi_value,
            'Station': station,
            'During_Rain': (time_point >= start_time) and (time_point <= end_time),
            'Hours_After_Start': (time_point - start_time).total_seconds() / 3600,
            'Hours_After_End': (time_point - end_time).total_seconds() / 3600
        }
        ndvi_data.append(record)

    # 转换为DataFrame
    df = pd.DataFrame(ndvi_data)

    # 添加事件信息
    df['Event_ID'] = event['Event_ID']
    df['Intensity_Class'] = event['Intensity_Class']
    df['Duration_Group'] = event['Duration_Group']
    df['Duration_hours'] = event['Duration_hours']

    return df


def process_single_hour(hour, hour_events):
    """处理单个小时的所有降雨事件（多线程工作函数）"""
    hour_str = hour.strftime("%Y%m%d%H")
    output_file = os.path.join(TEMP_DATA_DIR, f"ndvi_data_{hour_str}.parquet")

    # 如果文件已存在，跳过处理
    if os.path.exists(output_file):
        print(f"跳过已处理的小时: {hour}")
        return hour, True

    # 处理该小时的数据
    all_windows = []
    for _, event in hour_events.iterrows():
        event_data = extract_ndvi_for_event(event)
        all_windows.append(event_data)

    if all_windows:
        hour_data = pd.concat(all_windows, ignore_index=True)
        hour_data.to_parquet(output_file)
        print(f"已保存 {hour} 的数据: {output_file}")
        return hour, True
    return hour, False


def main():
    """主函数：执行多线程数据提取"""
    # 设置分析时间范围
    start_date = date(2015, 7, 7)
    end_date = date(2015, 12, 31)

    print(f"数据提取设置:")
    print(f"- 开始日期: {start_date}")
    print(f"- 结束日期: {end_date}")
    print(f"- NDVI小时范围: {NDVI_HOURS}")
    print(f"- 最大线程数: {MAX_WORKERS}")

    # 检查是否有未完成的任务
    saved_start, saved_end, processed_hours = load_processing_state()
    resume = False

    if saved_start and saved_end:
        if saved_start == start_date and saved_end == end_date:
            print(f"检测到未完成的任务，从断点继续...")
            resume = True
        else:
            print(f"检测到不同的任务范围，清除旧状态...")
            clear_processing_state()

    # 加载并过滤降雨事件数据（24小时全时段）
    rain_events = load_rain_events(start_date, end_date)

    if rain_events.empty:
        print("没有可分析的降雨事件，退出程序")
        return

    # 添加小时列用于分组
    rain_events['Hour'] = rain_events['Start_Time'].dt.floor('H')

    # 按小时分组
    hour_groups = rain_events.groupby('Hour')
    all_hours = sorted(hour_groups.groups.keys())

    # 如果需要恢复，跳过已处理的小时
    if resume:
        hours_to_process = [h for h in all_hours if h not in processed_hours]
    else:
        hours_to_process = all_hours
        processed_hours = []

    if not hours_to_process:
        print("所有小时的数据已处理，跳过数据提取阶段")
        return

    print(f"需要处理 {len(hours_to_process)} 小时的数据")
    save_processing_state(start_date, end_date, processed_hours)

    # 创建线程池
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 准备任务队列
        futures = {}
        for hour in hours_to_process:
            hour_events = hour_groups.get_group(hour)
            future = executor.submit(process_single_hour, hour, hour_events)
            futures[future] = hour

        # 处理完成的任务
        completed = 0
        for future in tqdm(concurrent.futures.as_completed(futures), total=len(futures),
                           desc="多线程处理小时数据"):
            hour = futures[future]
            try:
                processed_hour, success = future.result()
                if success:
                    # 更新已处理小时列表（线程安全）
                    with state_lock:
                        processed_hours.append(processed_hour)
                        completed += 1
                        # 每完成5个任务保存一次状态
                        if completed % 5 == 0:
                            save_processing_state(start_date, end_date, processed_hours)
            except Exception as e:
                print(f"处理小时 {hour} 时出错: {str(e)}")
                # 记录错误但继续处理其他任务

    # 最终保存状态
    save_processing_state(start_date, end_date, processed_hours)
    print(f"数据提取完成！处理了 {len(processed_hours)} 小时的数据")
    print(f"所有结果已保存到: {TEMP_DATA_DIR}")


if __name__ == "__main__":
    main()