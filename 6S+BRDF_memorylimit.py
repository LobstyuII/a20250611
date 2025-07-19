# python 6S+BRDF_ulti.py --shard-id 0 --total-shards 3
# python 6S+BRDF_ulti.py --shard-id 1 --total-shards 3
# python 6S+BRDF_ulti.py --shard-id 2 --total-shards 3

import os
import time
import netCDF4 as nc
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from Py6S import *
import multiprocessing
import argparse
from multiprocessing import shared_memory
import resource
import psutil
import gc

# 路径配置
PATHS = {
    "hourly_sozSR": "D:/H8_data/Hourly_sozSR_Angles/",
    "merra2_slv": "D:/H8_data/MERRA2_slv/",
    "merra2_aer": "D:/H8_data/MERRA2_aer/",
    "lucc": "D:/H8_data/LC_2015_2024.nc",
    "output": "D:/H8_Data/H8SR/",
    "luts": "D:/H8_data/LUTs.nc",
}

# 波段配置
BAND_WAVELENGTHS = [0.47, 0.51, 0.64, 0.86, 1.6, 2.3]
BAND_NAMES = ['Albedo_01', 'Albedo_02', 'Albedo_03', 'Albedo_04', 'Albedo_05', 'Albedo_06']
ANGLE_NAMES = ['SAZ', 'SAA', 'SOZ', 'SOA']

# 处理范围
START_DATE = datetime(2016, 1, 1)
END_DATE = datetime(2016, 12, 31)
PROCESS_HOURS = list(range(0, 12)) + list(range(21, 23))

# LUCC到BRDF映射 (保持不变)
LUCC_TO_BRDF = {
    1: {"model": "Rahman", "intensity": 0.3, "asymmetry": 0.1, "structural": 0.5},
    2: {"model": "Rahman", "intensity": 0.35, "asymmetry": 0.12, "structural": 0.55},
    # ... (其他映射保持不变)
}

# 大气廓线映射 (保持不变)
LATITUDE_TO_PROFILE = {
    (-90, -30): {5: AtmosProfile.SubarcticWinter, 9: AtmosProfile.SubarcticSummer},
    # ... (其他映射保持不变)
}


def set_memory_limit(percentage=0.75):
    """设置内存使用限制"""
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        total_mem = psutil.virtual_memory().total
        mem_limit = int(total_mem * percentage)
        resource.setrlimit(resource.RLIMIT_AS, (mem_limit, hard))
    except Exception as e:
        print(f"[{timestamp()}] [WARNING] Memory limit setting failed: {str(e)}")


def print_memory_usage():
    """打印当前内存使用情况"""
    process = psutil.Process(os.getpid())
    print(f"[{timestamp()}] Memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_netcdf(file_path, variables):
    """高效加载NetCDF数据 (保持不变)"""
    # ... (保持不变)


def get_atmos_profile(lat, date):
    """根据纬度和日期获取大气廓线 (保持不变)"""
    # ... (保持不变)


def set_brdf_model(s, lucc_value):
    """设置BRDF模型 (保持不变)"""
    # ... (保持不变)


def convert_merra2_units(to3, tqv):
    """转换MERRA2单位 (保持不变)"""
    # ... (保持不变)


def process_station_worker(task):
    """工作进程：处理单个站点 (增加内存保护)"""
    station, idx, hourly, merra2_slv, merra2_aer, lucc_dict, coords, date, result_idx = task

    try:
        # 初始化结果
        sr_results = np.full(len(BAND_WAVELENGTHS), np.nan, dtype=np.float32)
        gen_avail = 1
        valid_flag = 0

        # 检查数据可用性
        if hourly.get('hourly_availability', [1])[idx] != 0:
            return (result_idx, gen_avail, sr_results, valid_flag)

        gen_avail = 0

        # 获取角度
        angles = {}
        for angle in ANGLE_NAMES:
            angles[angle] = hourly.get(angle, [np.nan])[idx] if idx < len(hourly.get(angle, [])) else np.nan

        # 验证角度数据 - 增加SOZ角度阈值检查
        if any(np.isnan(angles[a]) for a in ANGLE_NAMES) or angles['SOZ'] > 65:
            return (result_idx, gen_avail, sr_results, valid_flag)

        # 获取大气参数
        to3 = merra2_slv.get('TO3', [np.nan])[idx] if idx < len(merra2_slv.get('TO3', [])) else np.nan
        tqv = merra2_slv.get('TQV', [np.nan])[idx] if idx < len(merra2_slv.get('TQV', [])) else np.nan
        ozone, water = convert_merra2_units(to3, tqv)

        # 获取AOT550值
        aot550 = merra2_aer.get('AOT550', [np.nan])[idx] if idx < len(merra2_aer.get('AOT550', [])) else np.nan

        # 计算TOA反射率
        cos_soz = np.cos(np.radians(angles['SOZ']))
        if cos_soz <= 0.01:
            cos_soz = 0.01

        toa_refs = []
        for band in BAND_NAMES:
            albedo = hourly.get(band, [np.nan])[idx] if idx < len(hourly.get(band, [])) else np.nan
            if np.isnan(albedo) or albedo < 0 or albedo > 1:
                toa_ref = np.nan
            else:
                toa_ref = albedo / cos_soz  # 将表观反射率转换为真实反射率
                toa_ref = np.clip(toa_ref, 0.0, 1.0)
            toa_refs.append(toa_ref)

        # 如果所有TOA反射率无效，直接返回
        if all(np.isnan(r) for r in toa_refs):
            return (result_idx, gen_avail, sr_results, valid_flag)

        # 创建独立的SixS实例
        s = SixS()
        s.outputs.suppress_stdout = True
        s.outputs.suppress_warnings = True
        s.altitudes.set_sensor_custom_altitude(99)
        s.aero_profile = AeroProfile.PredefinedType(AeroProfile.Continental)

        # 设置几何参数
        s.geometry = Geometry.User()
        s.geometry.solar_z = angles['SOZ']
        s.geometry.solar_a = angles['SOA']
        s.geometry.view_z = angles['SAZ']
        s.geometry.view_a = angles['SAA']

        # 设置大气参数
        if not np.isnan(water) and not np.isnan(ozone) and water > 0 and ozone > 0:
            s.atmos_profile = AtmosProfile.UserWaterAndOzone(water, ozone)
        else:
            s.atmos_profile = get_atmos_profile(lat, date)

        # 设置气溶胶
        if not np.isnan(aot550) and aot550 >= 0:
            s.aot550 = aot550

        # 设置BRDF
        lucc_value = lucc_dict.get(station, 255)
        s = set_brdf_model(s, lucc_value)

        # 处理每个波段
        for i, (wvl, refl) in enumerate(zip(BAND_WAVELENGTHS, toa_refs)):
            if np.isnan(refl) or refl < 0 or refl > 1:
                continue

            try:
                s.wavelength = Wavelength(wvl)
                s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(refl)
                s.run()
                sr_results[i] = s.outputs.pixel_reflectance
            except Exception as e:
                print(f"[{timestamp()}] [WARNING] Band {i} failed for station {station}: {str(e)}")
                sr_results[i] = np.nan

        # 如果至少有一个波段有效，则标记为有效
        if not all(np.isnan(sr_results)):
            valid_flag = 1

        return (result_idx, gen_avail, sr_results, valid_flag)

    except MemoryError:
        print(f"[{timestamp()}] [MEMORY ERROR] Process ran out of memory for station {station}")
        return (result_idx, 1, np.full(len(BAND_WAVELENGTHS), np.nan), 0)
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Processing failed for station {station}: {str(e)}")
        return (result_idx, 1, np.full(len(BAND_WAVELENGTHS), np.nan), 0)


def init_worker(shared_mem_name, shape):
    """初始化工作进程：连接共享内存"""
    global shared_array
    try:
        existing_shm = shared_memory.SharedMemory(name=shared_mem_name)
        shared_array = np.ndarray(shape, dtype=np.float32, buffer=existing_shm.buf)
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Worker init failed: {str(e)}")
        raise


def process_hour(date, hour, stations, lucc_dict, station_coords):
    """处理单小时数据 (改进的内存管理)"""
    # 设置内存限制
    set_memory_limit(0.75)

    date_str = date.strftime("%Y%m%d")
    hour_str = f"{hour * 100:04d}"
    time_key = f"{date_str}_{hour_str}"

    # 文件路径
    paths = {
        "sozSR": os.path.join(PATHS["hourly_sozSR"], date_str[:4], date_str[4:6],
                              f"H8_hourly_sozSR_angles_{time_key}.nc"),
        "merra_slv": os.path.join(PATHS["merra2_slv"], date_str[:4], date_str[4:6], f"MERRA2_{time_key}_TO3_TQV.nc"),
        "merra_aer": os.path.join(PATHS["merra2_aer"], date_str[:4], date_str[4:6], f"MERRA2_{time_key}_AOT550.nc"),
        "output": os.path.join(PATHS["output"], f"SR_{time_key}.nc")
    }

    # 检查输出文件
    if os.path.exists(paths["output"]):
        print(f"[{timestamp()}] [SKIPPED] Exists: {paths['output']}")
        return paths["output"], (0, 0, 0.0)

    # 检查输入文件
    missing_files = [p for p in [paths["sozSR"], paths["merra_slv"], paths["merra_aer"]] if not os.path.exists(p)]
    if missing_files:
        print(f"[{timestamp()}] [SKIPPED] Missing files for {time_key}: {', '.join(missing_files)}")
        return None, (0, 0, 0.0)

    # 加载数据
    print(f"[{timestamp()}] [INFO] Loading data for {time_key}")
    print_memory_usage()

    hourly = load_netcdf(paths["sozSR"], ['Station'] + BAND_NAMES + ANGLE_NAMES + ['hourly_availability'])
    merra2_slv = load_netcdf(paths["merra_slv"], ['Station', 'TO3', 'TQV'])
    merra2_aer = load_netcdf(paths["merra_aer"], ['Station', 'AOT550'])

    if None in [hourly, merra2_slv, merra2_aer]:
        print(f"[{timestamp()}] [ERROR] Data load failed for {time_key}")
        return None, (0, 0, 0.0)

    # 检查站点匹配
    hourly_stations = hourly.get('Station', [])
    station_idx = {s: i for i, s in enumerate(hourly_stations)}
    matched = [s for s in stations if s in station_idx]

    if not matched:
        print(f"[{timestamp()}] [WARNING] No stations matched for {time_key}")
        return None, (0, 0, 0.0)

    # 准备结果数组
    station_map = {s: i for i, s in enumerate(stations)}
    num_stations = len(stations)

    # 创建共享内存 (存储波段结果)
    sr_shape = (num_stations, len(BAND_WAVELENGTHS))
    sr_shm = None
    flags_shm = None

    try:
        sr_shm = shared_memory.SharedMemory(create=True, size=int(np.prod(sr_shape) * int(np.float32().itemsize)))
        sr_array = np.ndarray(sr_shape, dtype=np.float32, buffer=sr_shm.buf)
        sr_array[:] = np.nan

        # 创建共享内存 (存储标志)
        flags_shape = (num_stations, 2)  # [gen_avail, valid_flag]
        flags_shm = shared_memory.SharedMemory(create=True, size=int(np.prod(flags_shape) * int(np.int8().itemsize)))
        flags_array = np.ndarray(flags_shape, dtype=np.int8, buffer=flags_shm.buf)
        flags_array[:] = -1  # 初始化为-1

        # 准备任务
        tasks = [(station, station_idx[station], hourly, merra2_slv, merra2_aer, lucc_dict, station_coords, date,
                  station_map[station])
                 for station in matched]

        # 并行处理
        start_time = time.time()
        valid_count = 0
        total_matched = len(matched)

        # 分批处理任务 (每批100个站点)
        batch_size = 100
        with ProcessPoolExecutor(
                max_workers=min(6, multiprocessing.cpu_count()),  # 减少工作进程数
                initializer=init_worker,
                initargs=(sr_shm.name, sr_shape)
        ) as executor:
            for i in range(0, len(tasks), batch_size):
                batch = tasks[i:i + batch_size]
                futures = {executor.submit(process_station_worker, task): task for task in batch}

                for future in as_completed(futures):
                    try:
                        result_idx, gen_avail, sr_results, valid_flag = future.result()
                        sr_array[result_idx] = sr_results
                        flags_array[result_idx, 0] = gen_avail
                        flags_array[result_idx, 1] = valid_flag
                        if valid_flag == 1:
                            valid_count += 1
                    except Exception as e:
                        print(f"[{timestamp()}] [ERROR] Task failed: {str(e)}")

                # 每批处理完后强制垃圾回收
                gc.collect()
                print_memory_usage()

        # 复制结果到本地内存
        sr_results_local = sr_array.copy()
        gen_avail_local = flags_array[:, 0].copy()
        valid_flags_local = flags_array[:, 1].copy()

        # 保存结果
        os.makedirs(os.path.dirname(paths["output"]), exist_ok=True)
        with nc.Dataset(paths["output"], 'w') as ds:
            ds.createDimension('station', num_stations)
            station_var = ds.createVariable('Station', str, ('station',))
            station_var[:] = np.array(stations, dtype=object)

            gen_var = ds.createVariable('General_availability', 'i1', ('station',))
            gen_var[:] = gen_avail_local

            valid_var = ds.createVariable('valid_flag', 'i1', ('station',))
            valid_var[:] = valid_flags_local

            for i, band in enumerate(BAND_NAMES):
                band_var = ds.createVariable(band, 'f4', ('station',))
                band_var[:] = sr_results_local[:, i]
                band_var.units = "reflectance"

            ds.date_created = timestamp()
            ds.title = 'Himawari-8 Surface Reflectance'
            ds.time = hour_str
            ds.date = date_str
            ds.source = "6S atmospheric correction with BRDF"

        ratio = valid_count / total_matched if total_matched > 0 else 0
        elapsed = time.time() - start_time
        print(
            f"[{timestamp()}] [SUCCESS] Saved {paths['output']} - Valid: {valid_count}/{total_matched} ({ratio:.1%}) in {elapsed:.1f}s")
        return paths["output"], (valid_count, total_matched, ratio)

    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Processing failed for {time_key}: {str(e)}")
        return None, (0, 0, 0.0)

    finally:
        # 确保共享内存被清理
        if sr_shm is not None:
            sr_shm.close()
            sr_shm.unlink()
        if flags_shm is not None:
            flags_shm.close()
            flags_shm.unlink()
        gc.collect()


# ... (load_lucc, load_coords函数保持不变)

def main():
    """主处理函数 - 使用任务分片机制 (增加内存监控)"""
    start = time.time()
    print(f"[{timestamp()}] [START] Processing from {START_DATE} to {END_DATE}")
    print_memory_usage()

    # 准备目录
    os.makedirs(PATHS["output"], exist_ok=True)

    # 加载基础数据
    print(f"[{timestamp()}] [INFO] Loading station data...")
    station_coords = load_coords()
    if not station_coords:
        print(f"[{timestamp()}] [ERROR] No station coordinates")
        return

    stations = list(station_coords.keys())
    print(f"[{timestamp()}] [INFO] Loaded {len(stations)} stations")

    lucc_dict = load_lucc()
    if not lucc_dict:
        print(f"[{timestamp()}] [ERROR] No LUCC data")
        return

    # 生成日期列表
    dates = []
    current = START_DATE
    while current <= END_DATE:
        dates.append(current)
        current += timedelta(days=1)

    # 准备任务
    tasks = []
    for date in dates:
        for hour in PROCESS_HOURS:
            tasks.append((date, hour, stations, lucc_dict, station_coords))

    print(f"[{timestamp()}] [INFO] Total tasks: {len(tasks)}")

    # 解析命令行参数
    parser = argparse.ArgumentParser(description='POI校正任务分片处理')
    parser.add_argument('--shard-id', type=int, default=0, help='当前分片的ID')
    parser.add_argument('--total-shards', type=int, default=1, help='总分片数')
    args = parser.parse_args()

    # 任务分片
    total_tasks = len(tasks)
    shard_size = total_tasks // args.total_shards
    start_idx = args.shard_id * shard_size
    end_idx = start_idx + shard_size

    if args.shard_id == args.total_shards - 1:
        end_idx = total_tasks

    tasks = tasks[start_idx:end_idx]
    print(
        f"[{timestamp()}] [SHARD] Processing tasks {start_idx + 1}-{end_idx} of {total_tasks} (Shard {args.shard_id + 1}/{args.total_shards})")

    # 处理任务
    processed = []
    total_valid = 0
    total_stations = 0

    for task in tasks:
        date, hour, *_ = task
        time_key = f"{date.strftime('%Y%m%d')}_{hour * 100:04d}"
        print(f"[{timestamp()}] [PROCESSING] {time_key}")
        print_memory_usage()

        result, stats = process_hour(*task)
        if result:
            processed.append(result)
            v, t, _ = stats
            total_valid += v
            total_stations += t

        # 每个任务后垃圾回收
        gc.collect()

    # 最终统计
    hours = (time.time() - start) / 3600
    ratio = total_valid / total_stations if total_stations else 0

    print(f"\n[{timestamp()}] [SUMMARY] Processing completed for shard {args.shard_id}")
    print(f"  Processed files: {len(processed)}")
    print(f"  Total stations: {total_stations}")
    print(f"  Valid stations: {total_valid} ({ratio:.1%})")
    print(f"  Total time: {hours:.2f} hours")


if __name__ == "__main__":
    # 设置多进程启动方法
    multiprocessing.set_start_method('spawn', force=True)
    main()