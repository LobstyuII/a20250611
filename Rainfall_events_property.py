import os
import glob
import xarray as xr
import pandas as pd
import numpy as np
from tqdm import tqdm
import multiprocessing as mp
from functools import partial
import re
from datetime import datetime

# 配置参数
BASE_PATH = r"D:\H8_data\ERA5"  # ERA5数据根目录
OUTPUT_FILE = r"D:\H8_data\rain_events_all_stations.parquet"  # 输出文件路径
RAIN_THRESHOLD = 0.1  # 有效降雨阈值(mm)
DRY_HOURS = 1  # 最小无雨间隔(小时)
YEARS = range(2015, 2021)  # 根据实际数据年份修改
N_CORES = mp.cpu_count()  # 使用的CPU核心数


def classify_precipitation(total_rain, max_intensity, duration):
    """
    根据国家气象局标准分类降水强度
    :param total_rain: 事件总降雨量(mm)
    :param max_intensity: 最大小时降雨强度(mm/h)
    :param duration: 事件持续时间(小时)
    :return: 降水强度等级
    """
    if duration < 12:
        # 不足12小时：按最大小时强度换算为24小时总量
        virtual_24h_rain = max_intensity * 24
        rain_for_class = virtual_24h_rain
    else:
        # 12小时以上：直接使用事件总降雨量
        rain_for_class = total_rain

    # 根据24小时降水总量标准分类
    if rain_for_class < 10.0:
        return "小雨"
    elif rain_for_class < 25.0:
        return "中雨"
    elif rain_for_class < 50.0:
        return "大雨"
    elif rain_for_class < 100.0:
        return "暴雨"
    elif rain_for_class < 250.0:
        return "大暴雨"
    else:
        return "特大暴雨"


def detect_rain_events(station_data, rain_threshold, dry_hours):
    """
    检测单个站点的降雨事件并计算属性
    :param station_data: 站点时间序列数据
    :param rain_threshold: 有效降雨阈值(mm)
    :param dry_hours: 最小无雨间隔(小时)
    :return: 降雨事件属性DataFrame
    """
    # 确保按时间排序
    df = station_data.sort_values('Time').reset_index(drop=True)

    # 标记有效降雨小时
    df['IsRain'] = df['Precipitation_mm'] > rain_threshold

    # 识别降雨状态变化点
    df['RainChange'] = df['IsRain'].astype(int).diff()
    start_indices = df.index[df['RainChange'] == 1].tolist()
    stop_indices = df.index[df['RainChange'] == -1].tolist()

    # 处理边界情况
    if df['IsRain'].iloc[0]:
        start_indices.insert(0, 0)
    if df['IsRain'].iloc[-1]:
        stop_indices.append(len(df) - 1)

    # 配对开始和结束点
    events = []
    current_start = None

    for i in range(len(df)):
        if i in start_indices:
            current_start = i
        elif i in stop_indices and current_start is not None:
            # 检查是否满足最小无雨间隔
            if i + dry_hours <= len(df) - 1:
                next_hours = df.iloc[i:i + dry_hours]
                if not next_hours['IsRain'].any():
                    events.append((current_start, i))
                    current_start = None
            else:  # 数据结尾处理
                events.append((current_start, len(df) - 1))
                current_start = None

    # 处理最后一个未结束的事件
    if current_start is not None:
        events.append((current_start, len(df) - 1))

    # 计算每个事件的属性
    event_list = []

    for start_idx, end_idx in events:
        event_data = df.iloc[start_idx:end_idx + 1]
        start_time = event_data['Time'].min()
        end_time = event_data['Time'].max()
        duration = (end_time - start_time).total_seconds() / 3600 + 1
        total_rain = event_data['Precipitation_mm'].sum()
        avg_intensity = total_rain / duration
        max_intensity = event_data['Precipitation_mm'].max()
        rainy_hours = event_data['IsRain'].sum()

        # 分类降水强度
        intensity_class = classify_precipitation(total_rain, max_intensity, duration)

        event_list.append({
            'Station': df['Station'].iloc[0],
            'Start_Time': start_time,
            'End_Time': end_time,
            'Duration_hours': duration,
            'Total_Rain_mm': total_rain,
            'Avg_Intensity_mmh': avg_intensity,
            'Max_Intensity_mmh': max_intensity,
            'Rainy_Hours': rainy_hours,
            'Intensity_Class': intensity_class
        })

    return pd.DataFrame(event_list)


def parse_time_from_filename(filename):
    """
    从文件名解析时间信息
    格式: ERA5_YYYYMMDD_HH00.nc
    """
    # 提取文件名中的日期时间部分
    match = re.search(r"ERA5_(\d{8})_(\d{4})\.nc", os.path.basename(filename))
    if match:
        date_str = match.group(1)
        time_str = match.group(2)[:2]  # 只取小时部分
        return datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H")
    return None


def process_year(year):
    """
    处理单一年份的数据
    :param year: 年份
    :return: 该年份所有站点的降雨事件DataFrame
    """
    print(f"Processing year: {year}")
    year_path = os.path.join(BASE_PATH, str(year))
    all_files = []

    # 收集该年份所有文件
    for month in os.listdir(year_path):
        month_path = os.path.join(year_path, month)
        if os.path.isdir(month_path):
            nc_files = glob.glob(os.path.join(month_path, "ERA5_*.nc"))
            all_files.extend(nc_files)

    # 读取并处理所有文件
    data_frames = []
    for file in tqdm(all_files, desc=f"Reading {year} files"):
        try:
            # 从文件名解析时间
            file_time = parse_time_from_filename(file)
            if not file_time:
                print(f"Warning: Cannot parse time from filename: {file}, skipping")
                continue

            # 读取NetCDF文件
            ds = xr.open_dataset(file)
            df = ds[['Station', 'total_precipitation']].to_dataframe()
            df['Time'] = file_time  # 使用从文件名解析的时间
            df['Precipitation_mm'] = df['total_precipitation'] * 1000  # 米转毫米

            # 处理缺失值
            df['Precipitation_mm'] = df['Precipitation_mm'].replace(-9999.0, np.nan)
            df['Precipitation_mm'] = df['Precipitation_mm'].fillna(0)

            data_frames.append(df.reset_index()[['Station', 'Time', 'Precipitation_mm']])
        except Exception as e:
            print(f"Error processing {file}: {str(e)}")

    if not data_frames:
        return pd.DataFrame()

    # 合并年度数据
    year_data = pd.concat(data_frames, ignore_index=True)

    # 按站点分组处理
    grouped = year_data.groupby('Station')
    results = []

    # 使用多进程处理每个站点
    with mp.Pool(processes=N_CORES) as pool:
        func = partial(detect_rain_events, rain_threshold=RAIN_THRESHOLD, dry_hours=DRY_HOURS)
        results = list(tqdm(pool.imap(func, [group for _, group in grouped]),
                            total=len(grouped),
                            desc=f"Processing stations {year}"))

    # 合并所有事件
    if results:
        all_events = pd.concat(results, ignore_index=True)
        all_events['Year'] = year
        return all_events
    return pd.DataFrame()


def main():
    """主函数：处理所有年份数据并保存结果"""
    all_events = pd.DataFrame()

    # 处理每一年份
    for year in YEARS:
        year_events = process_year(year)
        if not year_events.empty:
            all_events = pd.concat([all_events, year_events], ignore_index=True)

    # 保存最终结果
    if not all_events.empty:
        all_events.to_parquet(OUTPUT_FILE, index=False)
        print(f"Saved results to {OUTPUT_FILE}")

        # 输出统计信息
        station_count = all_events['Station'].nunique()
        event_count = len(all_events)
        print(f"\nProcessing completed:")
        print(f"- Total stations processed: {station_count}")
        print(f"- Total rain events detected: {event_count}")
        print(f"- Intensity class distribution:")
        print(all_events['Intensity_Class'].value_counts())

        # 保存CSV副本以便查看
        csv_output = OUTPUT_FILE.replace('.parquet', '.csv')
        all_events.to_csv(csv_output, index=False)
        print(f"CSV copy saved to {csv_output}")
    else:
        print("No rain events detected.")


if __name__ == "__main__":
    main()