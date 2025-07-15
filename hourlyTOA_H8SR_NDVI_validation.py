import os
import netCDF4 as nc
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from datetime import datetime, timedelta

# 配置参数
DATE = '20150710'  # 格式: YYYYMMDD
STATION_NAME = '1055A'  # 替换为实际站点名称
TOA_DIR = 'D:/H8_data/Hourly_TOA_Angles'  # TOA反射率数据目录
H8NDVI_DIR = 'D:/H8_Data/H8NDVI'  # H8 NDVI产品数据目录
MODIS_DIR = 'D:/H8_Data/MODIS_NDVI_unresampled'  # MODIS数据目录
OUTPUT_DIR = 'D:/H8_Data/NDVI_cross_validation/output_plots'  # 输出目录


def read_modis_data(date, station_name):
    """读取MODIS单日数据文件"""
    year = date[:4]
    month = date[4:6]
    file_path = os.path.join(MODIS_DIR, year, month, f'MODIS_NDVI_{date}.nc')

    try:
        ds = nc.Dataset(file_path)
        stations = ds.variables['Station'][:]
        station_names = [''.join(s).strip() for s in stations]

        if station_name not in station_names:
            print(f"警告: 站点 '{station_name}' 未在MODIS数据中找到")
            return None, None, None, None

        idx = station_names.index(station_name)

        # 获取NDVI值
        terra_ndvi = ds.variables['NDVI_Terra'][idx]
        aqua_ndvi = ds.variables['NDVI_Aqua'][idx]

        # 处理缺失值
        if terra_ndvi == -9999.0 or np.isnan(terra_ndvi):
            terra_ndvi = np.nan
        if aqua_ndvi == -9999.0 or np.isnan(aqua_ndvi):
            aqua_ndvi = np.nan

        # 创建北京时间 (UTC+8)
        date_obj = datetime.strptime(date, '%Y%m%d')
        terra_time = datetime(date_obj.year, date_obj.month, date_obj.day, 10, 0)  # 北京时间10:00
        aqua_time = datetime(date_obj.year, date_obj.month, date_obj.day, 13, 0)  # 北京时间13:00

        return terra_time, terra_ndvi, aqua_time, aqua_ndvi

    except FileNotFoundError:
        print(f"错误: MODIS文件未找到: {file_path}")
        return None, None, None, None
    except Exception as e:
        print(f"读取MODIS数据时出错: {e}")
        return None, None, None, None


def read_toa_data(date, station_name):
    """读取TOA数据并计算NDVI，支持跨UTC日期的北京时间范围"""
    toa_times = []
    toa_ndvi = []
    year = date[:4]
    month = date[4:6]

    # 计算前一天日期
    date_dt = datetime.strptime(date, '%Y%m%d')
    prev_date_dt = date_dt - timedelta(days=1)
    prev_date = prev_date_dt.strftime('%Y%m%d')
    prev_year = prev_date[:4]
    prev_month = prev_date[4:6]

    # 定义要读取的时间范围
    time_ranges = [
        (prev_date, prev_year, prev_month, [21, 22, 23]),  # 前一天21-23UTC (北京时间5-7点)
        (date, year, month, list(range(0, 14)))  # 当天0-13UTC (北京时间8-21点)
    ]

    for date_str, year_str, month_str, utc_hours in time_ranges:
        for utc_hour in utc_hours:
            hh = str(utc_hour).zfill(2)
            file_path = os.path.join(TOA_DIR, year_str, month_str, f'H8_hourly_TOA_angles_{date_str}_{hh}00.nc')

            if not os.path.exists(file_path):
                continue

            try:
                ds = nc.Dataset(file_path)
                stations = ds.variables['Station'][:]
                station_names = [''.join(s).strip() for s in stations]

                if station_name not in station_names:
                    continue

                idx = station_names.index(station_name)

                # 检查数据可用性
                avail = ds.variables['hourly_availability'][idx]
                if avail != 0:
                    continue

                # 获取波段反射率
                band3 = ds.variables['Albedo_03'][idx]  # 红波段
                band4 = ds.variables['Albedo_04'][idx]  # 近红外波段

                # 计算NDVI
                denominator = band4 + band3
                if denominator > 0.01:  # 避免除以零
                    ndvi_val = (band4 - band3) / denominator
                else:
                    ndvi_val = np.nan

                # 检查NDVI有效性
                if np.isnan(ndvi_val) or ndvi_val < -1.0 or ndvi_val > 1.0:
                    continue

                # 转换为北京时间 (UTC+8)
                utc_time = datetime.strptime(f"{date_str}{hh}", '%Y%m%d%H')
                bj_time = utc_time + timedelta(hours=8)

                toa_times.append(bj_time)
                toa_ndvi.append(ndvi_val)

            except Exception as e:
                print(f"读取TOA文件 {file_path} 时出错: {e}")

    # 按时间排序
    sorted_indices = np.argsort(toa_times)
    toa_times_sorted = [toa_times[i] for i in sorted_indices]
    toa_ndvi_sorted = [toa_ndvi[i] for i in sorted_indices]

    return toa_times_sorted, toa_ndvi_sorted


def read_h8ndvi_data(date, station_name):
    """读取H8 NDVI产品数据，支持跨UTC日期的北京时间范围"""
    h8ndvi_times = []
    h8ndvi_values = []

    # 计算前一天日期
    date_dt = datetime.strptime(date, '%Y%m%d')
    prev_date_dt = date_dt - timedelta(days=1)
    prev_date = prev_date_dt.strftime('%Y%m%d')

    # 定义要读取的时间范围
    time_ranges = [
        (prev_date, [21, 22, 23]),  # 前一天21-23UTC (北京时间5-7点)
        (date, list(range(0, 14)))  # 当天0-13UTC (北京时间8-21点)
    ]

    for date_str, utc_hours in time_ranges:
        for utc_hour in utc_hours:
            hh = str(utc_hour).zfill(2)
            file_name = f'NDVI_{date_str}_{hh}00.nc'
            file_path = os.path.join(H8NDVI_DIR, file_name)

            if not os.path.exists(file_path):
                continue

            try:
                ds = nc.Dataset(file_path)
                stations = ds.variables['Station'][:]
                station_names = [''.join(s).strip() for s in stations]

                if station_name not in station_names:
                    continue

                idx = station_names.index(station_name)

                # 检查数据有效性
                valid_flag = ds.variables['valid_flag'][idx]
                if valid_flag == 0:
                    continue

                # 获取NDVI值
                ndvi_val = ds.variables['NDVI'][idx]
                if np.isnan(ndvi_val) or ndvi_val < -1.0 or ndvi_val > 1.0:
                    continue

                # 转换为北京时间 (UTC+8)
                utc_time = datetime.strptime(f"{date_str}{hh}", '%Y%m%d%H')
                bj_time = utc_time + timedelta(hours=8)

                h8ndvi_times.append(bj_time)
                h8ndvi_values.append(ndvi_val)

            except Exception as e:
                print(f"读取H8NDVI文件 {file_name} 时出错: {e}")

    # 按时间排序
    sorted_indices = np.argsort(h8ndvi_times)
    h8ndvi_times_sorted = [h8ndvi_times[i] for i in sorted_indices]
    h8ndvi_values_sorted = [h8ndvi_values[i] for i in sorted_indices]

    return h8ndvi_times_sorted, h8ndvi_values_sorted


def plot_ndvi_comparison(date, station_name):
    """绘制三种NDVI数据对比图"""
    # 读取所有数据
    terra_time, terra_ndvi, aqua_time, aqua_ndvi = read_modis_data(date, station_name)
    toa_times, toa_ndvi = read_toa_data(date, station_name)
    h8ndvi_times, h8ndvi_values = read_h8ndvi_data(date, station_name)

    # 检查是否有有效数据
    has_data = False
    data_sources = []

    if toa_ndvi:
        has_data = True
        data_sources.append("TOA")
    if h8ndvi_values:
        has_data = True
        data_sources.append("H8NDVI")
    if (terra_ndvi is not None and not np.isnan(terra_ndvi)) or \
            (aqua_ndvi is not None and not np.isnan(aqua_ndvi)):
        has_data = True
        data_sources.append("MODIS")

    if not has_data:
        print(f"错误: 没有找到 {station_name} 在 {date} 的有效NDVI数据")
        return

    # 创建图形和坐标轴
    fig, ax = plt.subplots(figsize=(14, 8))

    # 绘制H8TOA NDVI数据
    if toa_ndvi:
        ax.plot(toa_times, toa_ndvi, 'b-', linewidth=1.8, marker='o', markersize=6,
                label='Himawari-8 TOA NDVI', alpha=0.9, zorder=4)

    # 绘制H8NDVI产品数据
    if h8ndvi_values:
        ax.plot(h8ndvi_times, h8ndvi_values, 'r-', linewidth=1.8, marker='s', markersize=6,
                label='Himawari-8 NDVI Product', alpha=0.9, zorder=3)

    # 绘制MODIS Terra数据
    if terra_ndvi is not None and not np.isnan(terra_ndvi):
        ax.plot(terra_time, terra_ndvi, 'gD', markersize=10,
                label='Terra MODIS (10:00)', alpha=1.0, zorder=5)

    # 绘制MODIS Aqua数据
    if aqua_ndvi is not None and not np.isnan(aqua_ndvi):
        ax.plot(aqua_time, aqua_ndvi, 'mD', markersize=10,
                label='Aqua MODIS (13:00)', alpha=1.0, zorder=5)

    # 设置图形属性
    plt.title(f'NDVI Comparison at {station_name}\nDate: {date}', fontsize=16)
    plt.xlabel('Beijing Time (UTC+8)', fontsize=14)
    plt.ylabel('NDVI', fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.ylim(-0.2, 1.0)  # NDVI典型范围

    # 设置x轴时间范围（北京时间5:00-21:00）
    date_obj = datetime.strptime(date, '%Y%m%d')
    start_time = date_obj.replace(hour=5, minute=0)
    end_time = date_obj.replace(hour=21, minute=0)
    ax.set_xlim(start_time, end_time)

    # 设置x轴时间格式
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    fig.autofmt_xdate()

    # 添加图例
    ax.legend(loc='best', fontsize=12)

    # 添加数据点数量标注
    info_text = []
    if toa_ndvi:
        info_text.append(f'TOA Points: {len(toa_ndvi)}')
    if h8ndvi_values:
        info_text.append(f'H8NDVI Points: {len(h8ndvi_values)}')

    if info_text:
        info_str = "\n".join(info_text)
        ax.annotate(info_str,
                    xy=(0.02, 0.95), xycoords='axes fraction',
                    fontsize=11, bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8))

    # 添加统计信息框
    stats_text = []

    # 计算TOA和H8NDVI的平均值（如果两者都有数据）
    if toa_ndvi and h8ndvi_values:
        # 找出共同时间点
        common_times = set(toa_times) & set(h8ndvi_times)
        toa_common = [val for t, val in zip(toa_times, toa_ndvi) if t in common_times]
        h8_common = [val for t, val in zip(h8ndvi_times, h8ndvi_values) if t in common_times]

        if toa_common and h8_common:
            diff = np.array(toa_common) - np.array(h8_common)
            mean_diff = np.mean(diff)
            std_diff = np.std(diff)
            rmse = np.sqrt(np.mean(np.square(diff)))

            stats_text.append(f'TOA vs H8NDVI (n={len(common_times)}):')
            stats_text.append(f'Mean diff: {mean_diff:.4f}')
            stats_text.append(f'Std dev: {std_diff:.4f}')
            stats_text.append(f'RMSE: {rmse:.4f}')

    # 添加MODIS数据统计
    modis_vals = []
    if terra_ndvi is not None and not np.isnan(terra_ndvi):
        modis_vals.append(terra_ndvi)
    if aqua_ndvi is not None and not np.isnan(aqua_ndvi):
        modis_vals.append(aqua_ndvi)

    if modis_vals:
        modis_mean = np.mean(modis_vals)
        stats_text.append(f'\nMODIS Mean: {modis_mean:.4f}')

    if stats_text:
        stats_str = "\n".join(stats_text)
        ax.annotate(stats_str,
                    xy=(0.75, 0.95), xycoords='axes fraction',
                    fontsize=11, bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8))

    # 添加数据来源标签
    plt.figtext(0.5, 0.01, f"Data sources: {', '.join(data_sources)}",
                ha="center", fontsize=10, bbox={"facecolor": "white", "alpha": 0.7, "pad": 5})

    # 保存和显示图形
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f'FullDay_NDVI_Comparison_{station_name}_{date}.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"图形已保存至: {output_path}")
    # plt.close()
    plt.show()


# 执行绘图
plot_ndvi_comparison(DATE, STATION_NAME)