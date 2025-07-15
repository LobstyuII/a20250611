import os
import netCDF4 as nc
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed

# 更新路径配置 - 添加NDVI输出路径
PATHS = {
    "sr_input": "D:/H8_Data/H8SR/",  # SR文件输入路径
    "ndvi_output": "D:/H8_Data/H8NDVI/",  # NDVI输出路径
    "luts": "D:/H8_data/LUTs.nc"  # 站点坐标文件
}

# 处理的小时范围 (0-12时和21-23时)
PROCESS_HOURS = list(range(0, 13)) + list(range(21, 24))

# 日期范围
START_DATE = datetime(2015, 7, 7)
END_DATE = datetime(2015, 8, 6)


def get_current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_station_coords():
    """从LUTs.nc文件加载站点经纬度信息"""
    luts_file = PATHS["luts"]
    if not os.path.exists(luts_file):
        print(f"[{get_current_timestamp()}] [ERROR] LUTs file not found: {luts_file}")
        return {}

    try:
        with nc.Dataset(luts_file) as ds:
            station_var = ds.variables['Station']
            station_data = station_var[:]
            # 处理不同格式的站点数据
            if station_data.dtype.kind == 'S':  # 字节字符串
                stations = [s.tobytes().decode('utf-8').strip() for s in station_data]
            elif station_data.dtype.kind == 'U':  # Unicode字符串
                stations = [s.strip() for s in station_data]
            else:  # 其他类型
                stations = [str(s).strip() for s in station_data]

            # 使用正确的变量名 'Lat' 和 'Lon'
            lats = ds.variables['Lat'][:]
            lons = ds.variables['Lon'][:]

            # 转换为numpy数组并处理掩码值
            if isinstance(lats, np.ma.MaskedArray):
                lats = lats.filled(np.nan)
            if isinstance(lons, np.ma.MaskedArray):
                lons = lons.filled(np.nan)

            return {station: (lat, lon) for station, lat, lon in zip(stations, lats, lons)}
    except Exception as e:
        print(f"[{get_current_timestamp()}] [ERROR] Failed to load station coordinates: {str(e)}")
        return {}


def calculate_ndvi(red_band, nir_band):
    """计算NDVI并处理无效值"""
    # 初始化结果数组为NaN
    ndvi = np.full_like(red_band, np.nan, dtype=np.float32)

    # 计算分母 (NIR + Red)
    denominator = nir_band + red_band

    # 仅处理有效像素 (分母 > 0 且两个波段均为正数)
    valid_mask = (denominator > 0) & (red_band >= 0) & (nir_band >= 0) & \
                 (~np.isnan(red_band)) & (~np.isnan(nir_band))

    # 计算NDVI
    ndvi[valid_mask] = (nir_band[valid_mask] - red_band[valid_mask]) / denominator[valid_mask]

    # 确保NDVI在[-1, 1]范围内
    ndvi[ndvi < -1] = -1
    ndvi[ndvi > 1] = 1

    return ndvi


def process_hourly_ndvi(date, hour, stations_list):
    """处理单个小时的NDVI生成"""
    date_str = date.strftime("%Y%m%d")
    hour_str = f"{hour * 100:04d}"
    time_key = f"{date_str}_{hour_str}"

    # 输入SR文件路径
    sr_file = os.path.join(PATHS["sr_input"], f"SR_{time_key}.nc")

    # 输出NDVI文件路径
    ndvi_file = os.path.join(PATHS["ndvi_output"], f"NDVI_{time_key}.nc")

    # 检查SR文件是否存在
    if not os.path.exists(sr_file):
        print(f"[{get_current_timestamp()}] [SKIPPED] SR file not found: {sr_file}")
        return None

    # 检查输出文件是否已存在
    if os.path.exists(ndvi_file):
        print(f"[{get_current_timestamp()}] [SKIPPED] NDVI file already exists: {ndvi_file}")
        return ndvi_file

    try:
        # 读取SR文件
        with nc.Dataset(sr_file) as src:
            # 获取红波段和近红外波段
            red_band = src.variables['Albedo_03'][:]
            nir_band = src.variables['Albedo_04'][:]

            # 获取其他需要复制的变量
            stations = src.variables['Station'][:]
            gen_avail = src.variables['General_availability'][:]
            valid_flags = src.variables['valid_flag'][:]

            # 计算NDVI
            ndvi = calculate_ndvi(red_band, nir_band)

            # 计算NDVI有效像素比例
            valid_ndvi = np.count_nonzero(~np.isnan(ndvi))
            total_pixels = ndvi.size
            valid_ratio = valid_ndvi / total_pixels if total_pixels > 0 else 0

        # 创建输出目录
        os.makedirs(os.path.dirname(ndvi_file), exist_ok=True)

        # 写入NDVI文件
        with nc.Dataset(ndvi_file, 'w') as dst:
            # 创建维度
            dst.createDimension('station', len(stations_list))

            # 创建变量
            station_var = dst.createVariable('Station', str, ('station',))
            gen_avail_var = dst.createVariable('General_availability', np.int8, ('station',))
            valid_var = dst.createVariable('valid_flag', np.int8, ('station',))
            ndvi_var = dst.createVariable('NDVI', np.float32, ('station',))

            # 设置变量属性
            ndvi_var.units = "unitless"
            ndvi_var.long_name = "Normalized Difference Vegetation Index"
            ndvi_var.valid_range = np.array([-1.0, 1.0], dtype=np.float32)
            ndvi_var.description = "Calculated from surface reflectance bands 3 (0.64μm) and 4 (0.86μm)"

            # 写入数据
            station_var[:] = np.array(stations_list, dtype=object)
            gen_avail_var[:] = gen_avail
            valid_var[:] = valid_flags
            ndvi_var[:] = ndvi

            # 添加全局属性
            dst.date_created = get_current_timestamp()
            dst.title = 'Himawari-8 NDVI Product'
            dst.time = hour_str
            dst.date = date_str
            dst.source = f"Generated from SR file: {os.path.basename(sr_file)}"
            dst.author = "H8NDVI Processing System"
            dst.reference = "NDVI = (NIR - Red) / (NIR + Red)"
            dst.bands_used = "Red: Band 3 (0.64μm), NIR: Band 4 (0.86μm)"

        print(f"[{get_current_timestamp()}] [SUCCESS] Generated {ndvi_file} - "
              f"Valid NDVI pixels: {valid_ndvi}/{total_pixels} ({valid_ratio:.2%})")
        return ndvi_file

    except Exception as e:
        print(f"[{get_current_timestamp()}] [ERROR] Failed to process {time_key}: {str(e)}")
        return None


def main_ndvi():
    """主函数：生成NDVI产品"""
    print(f"[{get_current_timestamp()}] [START] NDVI processing started")

    # 创建输出目录
    os.makedirs(PATHS["ndvi_output"], exist_ok=True)

    # 加载站点坐标获取站点列表
    print(f"[{get_current_timestamp()}] [INFO] Loading station coordinates...")
    station_coords = load_station_coords()
    if not station_coords:
        print(f"[{get_current_timestamp()}] [ERROR] Failed to load station coordinates. Exiting.")
        return
    stations_list = list(station_coords.keys())
    print(f"[{get_current_timestamp()}] [INFO] Loaded {len(stations_list)} stations")

    # 生成日期列表
    date_list = []
    current_date = START_DATE
    while current_date <= END_DATE:
        date_list.append(current_date)
        current_date += timedelta(days=1)

    # 准备所有任务
    tasks = []
    for date in date_list:
        for hour in PROCESS_HOURS:
            tasks.append((date, hour, stations_list))

    print(f"[{get_current_timestamp()}] [INFO] Total tasks: {len(tasks)}")

    # 使用多进程处理
    processed_files = []
    total_valid = 0
    total_pixels = 0

    # 使用进程池
    max_workers = max(1, os.cpu_count() // 2)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_hourly_ndvi, *task): task for task in tasks}

        for future in as_completed(futures):
            date, hour, _ = futures[future]
            date_str = date.strftime("%Y%m%d")
            hour_str = f"{hour * 100:04d}"
            time_key = f"{date_str}_{hour_str}"

            try:
                result = future.result()
                if result:
                    processed_files.append(result)
                    # 这里可以添加更详细的统计
            except Exception as e:
                print(f"[{get_current_timestamp()}] [ERROR] Error processing {time_key}: {str(e)}")

    # 最终统计
    print(f"\n[{get_current_timestamp()}] [SUMMARY] NDVI processing completed")
    print(f"  Processed files: {len(processed_files)}")
    print(f"  Output directory: {PATHS['ndvi_output']}")


if __name__ == "__main__":
    main_ndvi()