# python 6S+BRDF.py

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
import gc
import traceback

# 路径配置
PATHS = {
    "hourly_sozSR": "D:/H8_data/Hourly_sozSR_Angles/",
    "merra2_slv": "D:/H8_data/MERRA2_slv/",
    "merra2_aer": "D:/H8_data/MERRA2_aer/",
    "lucc": "D:/H8_data/LC_2015_2024.nc",
    "output": "D:/H8_Data/H8SR/",
    "luts": "D:/H8_data/LUTs.nc",
}

# 波段配置 - 只保留波段3和4用于NDVI计算
BAND_WAVELENGTHS = [0.64, 0.86]
BAND_NAMES = ['Albedo_03', 'Albedo_04']
ANGLE_NAMES = ['SAZ', 'SAA', 'SOZ', 'SOA']

# 处理范围
START_DATE = datetime(2017, 1, 1)
END_DATE = datetime(2017, 12, 31)
PROCESS_HOURS = list(range(0, 12)) + list(range(21, 23))

# LUCC到BRDF映射
LUCC_TO_BRDF = {
    1: {"model": "Rahman", "intensity": 0.3, "asymmetry": 0.1, "structural": 0.5},
    2: {"model": "Rahman", "intensity": 0.35, "asymmetry": 0.12, "structural": 0.55},
    3: {"model": "Rahman", "intensity": 0.25, "asymmetry": 0.08, "structural": 0.45},
    4: {"model": "Rahman", "intensity": 0.3, "asymmetry": 0.1, "structural": 0.5},
    5: {"model": "Rahman", "intensity": 0.2, "asymmetry": 0.05, "structural": 0.4},
    6: {"model": "Rahman", "intensity": 0.4, "asymmetry": 0.15, "structural": 0.6},
    7: {"model": "Rahman", "intensity": 0.35, "asymmetry": 0.12, "structural": 0.55},
    8: {"model": "Walthall", "param1": 0.5, "param2": 0.2, "param3": 0.1, "albedo": 0.25},
    9: {"model": "Walthall", "param1": 0.4, "param2": 0.15, "param3": 0.05, "albedo": 0.3},
    10: {"model": "Lambertian", "albedo": 0.35},
    11: {"model": "Lambertian", "albedo": 0.1},
    12: {"model": "Lambertian", "albedo": 0.4},
    13: {"model": "Walthall", "param1": 0.6, "param2": 0.25, "param3": 0.15, "albedo": 0.35},
    14: {"model": "Lambertian", "albedo": 0.7},
    15: {"model": "Lambertian", "albedo": 0.05},
    16: {"model": "Lambertian", "albedo": 0.02},
    17: {"model": "Lambertian", "albedo": 0.02},
    255: {"model": "Lambertian", "albedo": 0.2}
}

# 大气廓线映射
LATITUDE_TO_PROFILE = {
    (-90, -30): {5: AtmosProfile.SubarcticWinter, 9: AtmosProfile.SubarcticSummer},
    (-30, 30): AtmosProfile.Tropical,
    (30, 60): {5: AtmosProfile.MidlatitudeWinter, 9: AtmosProfile.MidlatitudeSummer},
    (60, 90): {5: AtmosProfile.SubarcticWinter, 9: AtmosProfile.SubarcticSummer}
}

# 最大SOZ角度阈值
MAX_SOZ_ANGLE = 65


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_netcdf(file_path, variables):
    """高效加载NetCDF数据"""
    if not os.path.exists(file_path):
        print(f"[{timestamp()}] [WARNING] File not found: {file_path}")
        return None

    try:
        with nc.Dataset(file_path) as ds:
            data = {}
            for var in variables:
                if var not in ds.variables:
                    print(f"[{timestamp()}] [WARNING] Variable '{var}' not found in {file_path}")
                    data[var] = np.array([np.nan])
                    continue

                var_data = ds.variables[var][:]

                if var == 'Station':
                    if var_data.dtype.kind in ['S', 'U']:
                        data[var] = [str(s).strip() for s in var_data]
                    else:
                        data[var] = [str(s).strip() for s in var_data]
                else:
                    if isinstance(var_data, np.ma.MaskedArray):
                        var_data = var_data.filled(np.nan)

                    if var == 'AOT550':
                        var_data = np.where(var_data == -9999.0, np.nan, var_data)

                    data[var] = var_data
            return data
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Error loading {file_path}: {str(e)}")
        return None


def get_atmos_profile(lat, date):
    """根据纬度和日期获取大气廓线"""
    if np.isnan(lat):
        print(f"[{timestamp()}] [WARNING] Latitude is NaN, using default profile")
        return AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)

    for (low, high), profile in LATITUDE_TO_PROFILE.items():
        if low <= lat < high:
            if isinstance(profile, dict):
                month_group = 5 if date.month in range(5, 10) else 9
                selected_profile = profile[month_group]
                return AtmosProfile.PredefinedType(selected_profile)
            else:
                return AtmosProfile.PredefinedType(profile)

    print(f"[{timestamp()}] [WARNING] No profile found for lat {lat}, using default")
    return AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)


def set_brdf_model(s, lucc_value):
    """设置BRDF模型"""
    try:
        lucc_int = int(lucc_value)
        params = LUCC_TO_BRDF.get(lucc_int, LUCC_TO_BRDF[255])
    except (ValueError, TypeError):
        print(f"[{timestamp()}] [WARNING] Invalid LUCC value: {lucc_value}, using default")
        params = LUCC_TO_BRDF[255]

    try:
        if params["model"] == "Rahman":
            s.ground_reflectance = GroundReflectance.HomogeneousRahman(
                params["intensity"], params["asymmetry"], params["structural"])
        elif params["model"] == "Walthall":
            s.ground_reflectance = GroundReflectance.HomogeneousWalthall(
                params["param1"], params["param2"], params["param3"], params["albedo"])
        else:
            s.ground_reflectance = GroundReflectance.HomogeneousLambertian(params["albedo"])
        return s
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Failed to set BRDF model for LUCC {lucc_value}: {str(e)}")
        s.ground_reflectance = GroundReflectance.HomogeneousLambertian(0.2)
        return s


def convert_merra2_units(to3, tqv):
    """转换MERRA2单位"""
    if np.isnan(to3) or np.isnan(tqv):
        return np.nan, np.nan
    return to3 * 0.001, tqv * 0.1  # Dobson->cm-atm, kg/m²->g/cm²


def process_station_worker(task):
    """工作进程：处理单个站点 - 仅计算波段3和4"""
    station, idx, hourly, merra2_slv, merra2_aer, lucc_dict, coords, date, result_idx = task
    lat, lon = coords.get(station, (np.nan, np.nan))

    # 初始化结果
    sr_results = np.full(len(BAND_WAVELENGTHS), np.nan, dtype=np.float32)
    gen_avail = 1
    valid_flag = 0

    try:
        # 检查数据可用性
        if hourly.get('hourly_availability', [1])[idx] != 0:
            return (result_idx, gen_avail, sr_results, valid_flag)

        gen_avail = 0

        # 获取角度
        angles = {}
        for angle in ANGLE_NAMES:
            angles[angle] = hourly.get(angle, [np.nan])[idx] if idx < len(hourly.get(angle, [])) else np.nan

        # 验证角度数据 - 增加SOZ角度阈值检查
        if any(np.isnan(angles[a]) for a in ANGLE_NAMES) or angles['SOZ'] > MAX_SOZ_ANGLE:
            return (result_idx, gen_avail, sr_results, valid_flag)

        # 获取大气参数
        to3 = merra2_slv.get('TO3', [np.nan])[idx] if idx < len(merra2_slv.get('TO3', [])) else np.nan
        tqv = merra2_slv.get('TQV', [np.nan])[idx] if idx < len(merra2_slv.get('TQV', [])) else np.nan
        ozone, water = convert_merra2_units(to3, tqv)

        # 获取AOT550值
        aot550 = merra2_aer.get('AOT550', [np.nan])[idx] if idx < len(merra2_aer.get('AOT550', [])) else np.nan

        # 计算TOA反射率
        # 注意：输入的Albedo已经是表观反射率乘以cos(SOZ)，因此需要除以cos(SOZ)得到真实反射率
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
        try:
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

            # 只处理两个波段
            for i, (wvl, refl) in enumerate(zip(BAND_WAVELENGTHS, toa_refs)):
                if np.isnan(refl) or refl < 0 or refl > 1:
                    continue

                try:
                    s.wavelength = Wavelength(wvl)
                    s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(refl)
                    s.run()
                    sr_results[i] = s.outputs.pixel_reflectance
                except Exception as e:
                    print(f"[{timestamp()}] [WARNING] 6S failed for station {station} band {BAND_NAMES[i]}: {str(e)}")
                    sr_results[i] = np.nan

            # 如果至少有一个波段有效，则标记为有效
            if not all(np.isnan(sr_results)):
                valid_flag = 1

        finally:
            # 确保SixS实例被清理
            del s
            gc.collect()

    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Processing failed for station {station}: {str(e)}")
        traceback.print_exc()

    return (result_idx, gen_avail, sr_results, valid_flag)


def process_hour(date, hour, stations, lucc_dict, station_coords):
    """处理单小时数据 - 使用共享内存并行架构"""
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
    hourly = load_netcdf(paths["sozSR"], ['Station'] + BAND_NAMES + ANGLE_NAMES + ['hourly_availability'])
    merra2_slv = load_netcdf(paths["merra_slv"], ['Station', 'TO3', 'TQV'])
    merra2_aer = load_netcdf(paths["merra_aer"], ['Station', 'AOT550'])

    if None in [hourly, merra2_slv, merra2_aer]:
        print(f"[{timestamp()}] [ERROR] Data load failed for {time_key}")
        return None, (0, 0, 0.0)

    # 检查站点匹配
    hourly_stations = hourly.get('Station', [])
    merra2_slv_stations = merra2_slv.get('Station', [])
    merra2_aer_stations = merra2_aer.get('Station', [])

    # 创建站点索引
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
        sr_shm = shared_memory.SharedMemory(create=True, size=int(np.prod(sr_shape) * np.float32().itemsize))
        sr_array = np.ndarray(sr_shape, dtype=np.float32, buffer=sr_shm.buf)
        sr_array[:] = np.nan

        # 创建共享内存 (存储标志)
        flags_shape = (num_stations, 2)  # [gen_avail, valid_flag]
        flags_shm = shared_memory.SharedMemory(create=True, size=int(np.prod(flags_shape) * np.int8().itemsize))
        flags_array = np.ndarray(flags_shape, dtype=np.int8, buffer=flags_shm.buf)
        flags_array[:] = -1  # 初始化为-1

        # 准备任务
        tasks = []
        for station in matched:
            idx = station_idx[station]
            sidx = station_map[station]
            tasks.append((station, idx, hourly, merra2_slv, merra2_aer, lucc_dict, station_coords, date, sidx))

        # 并行处理
        start_time = time.time()
        valid_count = 0
        total_matched = len(matched)

        # 资源使用控制 - 根据服务器资源调整max_workers
        # 使用物理核心数而不是逻辑核心数
        physical_cores = os.cpu_count() // 2 if os.cpu_count() > 4 else os.cpu_count()
        max_workers = min(physical_cores, 12)  # 不超过12个进程

        print(f"[{timestamp()}] [INFO] Processing {len(tasks)} stations with {max_workers} workers")

        with ProcessPoolExecutor(
                max_workers=max_workers,
                initializer=init_worker,
                initargs=(sr_shm.name, sr_shape)
        ) as executor:
            futures = {executor.submit(process_station_worker, task): task for task in tasks}

            for future in as_completed(futures):
                try:
                    result_idx, gen_avail, sr_results, valid_flag = future.result()

                    # 更新共享内存
                    sr_array[result_idx] = sr_results
                    flags_array[result_idx, 0] = gen_avail
                    flags_array[result_idx, 1] = valid_flag

                    if valid_flag == 1:
                        valid_count += 1
                except Exception as e:
                    print(f"[{timestamp()}] [ERROR] Task failed: {str(e)}")
                    traceback.print_exc()

        # 复制结果到本地内存
        sr_results_local = sr_array.copy()
        gen_avail_local = flags_array[:, 0].copy()
        valid_flags_local = flags_array[:, 1].copy()

        # 保存结果
        try:
            os.makedirs(os.path.dirname(paths["output"]), exist_ok=True)
            with nc.Dataset(paths["output"], 'w') as ds:
                ds.createDimension('station', num_stations)

                # 站点变量
                station_var = ds.createVariable('Station', str, ('station',))
                station_var[:] = np.array(stations, dtype=object)

                # 可用性变量
                gen_var = ds.createVariable('General_availability', 'i1', ('station',))
                gen_var[:] = gen_avail_local

                # 有效性标志
                valid_var = ds.createVariable('valid_flag', 'i1', ('station',))
                valid_var[:] = valid_flags_local

                # 波段数据
                for i, band in enumerate(BAND_NAMES):
                    band_var = ds.createVariable(band, 'f4', ('station',))
                    band_var[:] = sr_results_local[:, i]
                    band_var.units = "reflectance"

                # 元数据
                ds.date_created = timestamp()
                ds.title = 'Himawari-8 Surface Reflectance (Band 3 & 4 only)'
                ds.time = hour_str
                ds.date = date_str
                ds.source = "6S atmospheric correction with BRDF"

            ratio = valid_count / total_matched if total_matched > 0 else 0
            elapsed = time.time() - start_time
            print(
                f"[{timestamp()}] [SUCCESS] Saved {paths['output']} - Valid: {valid_count}/{total_matched} ({ratio:.1%}) in {elapsed:.1f}s")
            return paths["output"], (valid_count, total_matched, ratio)
        except Exception as e:
            print(f"[{timestamp()}] [ERROR] Save failed for {paths['output']}: {str(e)}")
            return None, (0, 0, 0.0)

    finally:
        # 确保共享内存被清理
        if sr_shm:
            sr_shm.close()
            sr_shm.unlink()
        if flags_shm:
            flags_shm.close()
            flags_shm.unlink()


def init_worker(shared_mem_name, shape):
    """初始化工作进程：连接共享内存"""
    global shared_array
    try:
        existing_shm = shared_memory.SharedMemory(name=shared_mem_name)
        shared_array = np.ndarray(shape, dtype=np.float32, buffer=existing_shm.buf)
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Worker init failed: {str(e)}")
        raise


def load_lucc():
    """加载LUCC数据"""
    try:
        with nc.Dataset(PATHS["lucc"]) as ds:
            stations = [str(s).strip() for s in ds.variables['Station'][:]]
            lucc = ds.variables['LC_type1'][0, :]
            if isinstance(lucc, np.ma.MaskedArray):
                lucc = lucc.filled(255)
            lucc_dict = dict(zip(stations, lucc))
            print(f"[{timestamp()}] [INFO] Loaded LUCC for {len(lucc_dict)} stations")
            return lucc_dict
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] LUCC load failed: {str(e)}")
        return None


def load_coords():
    """加载站点坐标"""
    try:
        with nc.Dataset(PATHS["luts"]) as ds:
            stations = [str(s).strip() for s in ds.variables['Station'][:]]
            lats = ds.variables['Lat'][:]
            lons = ds.variables['Lon'][:]

            if isinstance(lats, np.ma.MaskedArray):
                lats = lats.filled(np.nan)
            if isinstance(lons, np.ma.MaskedArray):
                lons = lons.filled(np.nan)

            coords = {s: (lat, lon) for s, lat, lon in zip(stations, lats, lons)}
            print(f"[{timestamp()}] [INFO] Loaded coordinates for {len(coords)} stations")
            return coords
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Coords load failed: {str(e)}")
        return {}


def main():
    """主处理函数 - 移除分片机制"""
    start = time.time()
    print(f"[{timestamp()}] [START] Processing from {START_DATE} to {END_DATE}")

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

    # 处理任务
    processed = []
    total_valid = 0
    total_stations = 0

    for task in tasks:
        date, hour, *_ = task
        time_key = f"{date.strftime('%Y%m%d')}_{hour * 100:04d}"
        print(f"[{timestamp()}] [PROCESSING] {time_key}")

        result, stats = process_hour(*task)
        if result:
            processed.append(result)
            v, t, _ = stats
            total_valid += v
            total_stations += t

    # 最终统计
    hours = (time.time() - start) / 3600
    ratio = total_valid / total_stations if total_stations else 0

    print(f"\n[{timestamp()}] [SUMMARY] Processing completed")
    print(f"  Processed files: {len(processed)}")
    print(f"  Total stations: {total_stations}")
    print(f"  Valid stations: {total_valid} ({ratio:.1%})")
    print(f"  Total time: {hours:.2f} hours")


if __name__ == "__main__":
    # 设置多进程启动方法
    multiprocessing.set_start_method('spawn', force=True)
    main()