import os
import time
import netCDF4 as nc
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from Py6S import *
from queue import Queue

# 路径配置 - 新增MERRA2 AOT550路径
PATHS = {
    "hourly_toa": "D:/H8_data/Hourly_TOA_Angles/",
    "merra2": "D:/H8_data/MERRA2/",
    "merra2_aot550": "D:/H8_data/MERRA2_AOT550/",  # 新增AOT550路径
    "lucc": "D:/H8_data/LC_2015_2024.nc",
    "output": "D:/H8_Data/H8SR/",
    "luts": "D:/H8_data/LUTs.nc",
    # 移除原来的aod路径
}

# 波段配置
BAND_WAVELENGTHS = [0.47, 0.51, 0.64, 0.86]
BAND_NAMES = [f"Albedo_0{i + 1}" for i in range(0, 4)]
ANGLE_NAMES = ['SAZ', 'SAA', 'SOZ', 'SOA']

# 处理范围
START_DATE = datetime(2015, 7, 7)
END_DATE = datetime(2016, 12, 31)
PROCESS_HOURS = list(range(0, 13)) + list(range(21, 24))

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

# 预定义大气廓线映射
LATITUDE_TO_PROFILE = {
    (-90, -30): {5: AtmosProfile.SubarcticWinter, 9: AtmosProfile.SubarcticSummer},
    (-30, 30): AtmosProfile.Tropical,
    (30, 60): {5: AtmosProfile.MidlatitudeWinter, 9: AtmosProfile.MidlatitudeSummer},
    (60, 90): {5: AtmosProfile.SubarcticWinter, 9: AtmosProfile.SubarcticSummer}
}

# 对象池大小
SIXS_POOL_SIZE = 8


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SixSPool:
    """SixS对象池，重用SixS实例减少初始化开销"""

    def __init__(self, size=SIXS_POOL_SIZE):
        self.pool = Queue(maxsize=size)
        for _ in range(size):
            s = SixS()
            # 设置公共参数（不经常变化的参数）
            s.altitudes.set_sensor_custom_altitude(99)  # 设置传感器高度为99km
            s.aero_profile = AeroProfile.PredefinedType(AeroProfile.Continental)
            self.pool.put(s)

    def acquire(self):
        """从池中获取SixS实例"""
        return self.pool.get()

    def release(self, s):
        """释放SixS实例回池中"""
        # 重置状态但保留基础配置
        s.wavelength = None
        s.atmos_corr = None
        s.aot550 = None
        s.visibility = None
        s.atmos_profile = None
        s.ground_reflectance = None
        self.pool.put(s)


# 全局对象池
sixs_pool = SixSPool()


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
                    # 统一处理站点名称
                    if var_data.dtype.kind in ['S', 'U']:
                        data[var] = [str(s).strip() for s in var_data]
                    else:
                        data[var] = [str(s).strip() for s in var_data]
                else:
                    if isinstance(var_data, np.ma.MaskedArray):
                        var_data = var_data.filled(np.nan)

                    # 处理MERRA2的缺失值
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
                print(f"[{timestamp()}] [INFO] Selected profile {selected_profile} for lat {lat} in month {date.month}")
                return AtmosProfile.PredefinedType(selected_profile)
            else:
                print(f"[{timestamp()}] [INFO] Selected profile {profile} for lat {lat}")
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
    print("params = ", params)
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
        # 设置默认BRDF模型
        s.ground_reflectance = GroundReflectance.HomogeneousLambertian(0.2)
        return s


def convert_merra2_units(to3, tqv):
    """转换MERRA2单位"""
    if np.isnan(to3) or np.isnan(tqv):
        print(f"[{timestamp()}] [WARNING] Invalid MERRA2 values: TO3={to3}, TQV={tqv}")
        return np.nan, np.nan

    return to3 * 0.001, tqv * 0.1  # Dobson->cm-atm, kg/m²->g/cm²


def process_station(station_data):
    """处理单个站点"""
    station, idx, hourly, merra2, aot550_data, lucc_dict, coords, date = station_data
    lat, lon = coords.get(station, (np.nan, np.nan))

    # 检查可用性
    if hourly['hourly_availability'][idx] != 0:
        print(f"[{timestamp()}] [WARNING] Station {station} not available in hourly data")
        return station, 1, np.full(len(BAND_WAVELENGTHS), np.nan), 0

    # 获取大气参数
    to3 = merra2.get('TO3', [np.nan])[idx] if idx < len(merra2.get('TO3', [])) else np.nan
    tqv = merra2.get('TQV', [np.nan])[idx] if idx < len(merra2.get('TQV', [])) else np.nan
    ozone, water = convert_merra2_units(to3, tqv)

    # 直接获取AOT550值
    aot550 = aot550_data.get('AOT550', [np.nan])[idx] if idx < len(aot550_data.get('AOT550', [])) else np.nan

    # 获取角度
    angles = {}
    for angle in ANGLE_NAMES:
        angles[angle] = hourly.get(angle, [np.nan])[idx] if idx < len(hourly.get(angle, [])) else np.nan

    # 验证角度数据
    if any(np.isnan(angles[a]) for a in ANGLE_NAMES):
        print(f"[{timestamp()}] [WARNING] Station {station} has missing angles: {angles}")
        return station, 1, np.full(len(BAND_WAVELENGTHS), np.nan), 0

    # 计算TOA反射率
    cos_soz = np.cos(np.radians(angles['SOZ']))
    if cos_soz <= 0.01:
        print(f"[{timestamp()}] [WARNING] Invalid SOZ angle: {angles['SOZ']}, cos={cos_soz:.4f}")
        cos_soz = 0.01  # 防止除零错误

    toa_refs = []
    for band in BAND_NAMES:
        albedo = hourly.get(band, [np.nan])[idx] if idx < len(hourly.get(band, [])) else np.nan
        if np.isnan(albedo) or albedo < 0 or albedo > 1:
            print(f"[{timestamp()}] [WARNING] Station {station} has invalid {band}: {albedo}")
            toa_ref = np.nan
        else:
            toa_ref = albedo / cos_soz
            # 限制在合理范围
            toa_ref = np.clip(toa_ref, 0.0, 1.0)
        toa_refs.append(toa_ref)

    # 如果所有TOA反射率无效，直接返回
    if all(np.isnan(r) for r in toa_refs):
        print(f"[{timestamp()}] [WARNING] All TOA reflectances invalid for station {station}")
        return station, 1, np.full(len(BAND_WAVELENGTHS), np.nan), 0

    # 执行6S大气校正
    sr_results = np.full(len(BAND_WAVELENGTHS), np.nan, dtype=np.float32)
    valid_flag = 0

    try:
        # 从对象池获取SixS实例
        s = sixs_pool.acquire()

        # 设置几何参数
        s.geometry = Geometry.User()
        s.geometry.solar_z = angles['SOZ']
        s.geometry.solar_a = angles['SOA']
        s.geometry.view_z = angles['SAZ']
        s.geometry.view_a = angles['SAA']

        # 设置大气参数
        if not np.isnan(water) and not np.isnan(ozone) and water > 0 and ozone > 0:
            print(f"[{timestamp()}] [INFO] Using custom profile for station {station}: O3={ozone:.4f}, H2O={water:.4f}")
            s.atmos_profile = AtmosProfile.UserWaterAndOzone(water, ozone)
        else:
            profile = get_atmos_profile(lat, date)
            print(f"[{timestamp()}] [INFO] Using predefined profile for station {station}: {profile}")
            s.atmos_profile = profile

        # 设置气溶胶 - 直接使用AOT550
        if not np.isnan(aot550) and aot550 >= 0:
            print(f"[{timestamp()}] [INFO] Using AOT550={aot550:.4f} for station {station}")
            s.aot550 = aot550
        else:
            print(f"[{timestamp()}] [WARNING] Invalid AOT550 for station {station}: {aot550}")
            s.aot550 = None

        # 设置BRDF
        lucc_value = lucc_dict.get(station, 255)
        print("lucc_value = ", lucc_value)
        print(f"[{timestamp()}] [INFO] Setting BRDF for station {station} with LUCC={lucc_value}")
        s = set_brdf_model(s, lucc_value)

        # 处理每个波段
        for i, (wvl, refl) in enumerate(zip(BAND_WAVELENGTHS, toa_refs)):
            if np.isnan(refl) or refl < 0 or refl > 1:
                print(
                    f"[{timestamp()}] [WARNING] Skipping band {wvl} for station {station}: invalid reflectance {refl}")
                continue

            try:
                print(f"[{timestamp()}] [INFO] Processing band {wvl} for station {station} with refl={refl:.4f}")
                s.wavelength = Wavelength(wvl)
                s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(refl)
                s.run()
                sr_results[i] = s.outputs.pixel_reflectance
                print(f"[{timestamp()}] [SUCCESS] Band {wvl} result: {sr_results[i]:.6f}")
            except Exception as e:
                print(f"[{timestamp()}] [ERROR] Band {wvl} failed for station {station}: {str(e)}")
                sr_results[i] = np.nan

        valid_flag = 1
        print(f"[{timestamp()}] [SUCCESS] Processed station {station}: {sr_results}")
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Processing failed for station {station}: {str(e)}")
        print(f"  Angles: {angles}")
        print(f"  TOA Refl: {toa_refs}")
        print(f"  Ozone: {ozone}, Water: {water}")
        print(f"  AOT550: {aot550}")
        print(f"  LUCC: {lucc_dict.get(station, 'N/A')}")
    finally:
        # 确保将SixS实例归还给对象池
        if 's' in locals():
            sixs_pool.release(s)

    return station, 0, sr_results, valid_flag


def process_hour(date, hour, stations, lucc_dict, station_coords):
    """处理单小时数据"""
    date_str = date.strftime("%Y%m%d")
    hour_str = f"{hour * 100:04d}"
    time_key = f"{date_str}_{hour_str}"

    # 文件路径 - 使用MERRA2 AOT550替代原AOD数据
    paths = {
        "toa": os.path.join(PATHS["hourly_toa"], date_str[:4], date_str[4:6], f"H8_hourly_TOA_angles_{time_key}.nc"),
        "merra": os.path.join(PATHS["merra2"], date_str[:4], date_str[4:6], f"MERRA2_{time_key}_TO3_TQV.nc"),
        "aot550": os.path.join(PATHS["merra2_aot550"], date_str[:4], date_str[4:6], f"MERRA2_{time_key}_AOT550.nc"),
        "output": os.path.join(PATHS["output"], f"SR_{time_key}.nc")
    }

    # 检查输出文件
    if os.path.exists(paths["output"]):
        print(f"[{timestamp()}] [SKIPPED] Exists: {paths['output']}")
        return paths["output"], (0, 0, 0.0)

    # 检查输入文件
    missing_files = [p for p in [paths["toa"], paths["merra"], paths["aot550"]] if not os.path.exists(p)]
    if missing_files:
        print(f"[{timestamp()}] [SKIPPED] Missing files for {time_key}: {', '.join(missing_files)}")
        return None, (0, 0, 0.0)

    # 加载数据
    print(f"[{timestamp()}] [INFO] Loading data for {time_key}")
    hourly = load_netcdf(paths["toa"], ['Station'] + BAND_NAMES + ANGLE_NAMES + ['hourly_availability'])
    merra2 = load_netcdf(paths["merra"], ['Station', 'TO3', 'TQV'])
    aot550_data = load_netcdf(paths["aot550"], ['Station', 'AOT550'])  # 加载AOT550数据

    if None in [hourly, merra2, aot550_data]:
        print(f"[{timestamp()}] [ERROR] Data load failed for {time_key}")
        return None, (0, 0, 0.0)

    # 检查站点匹配
    hourly_stations = hourly.get('Station', [])
    merra2_stations = merra2.get('Station', [])
    aot_stations = aot550_data.get('Station', [])

    print(
        f"[{timestamp()}] [INFO] Stations: Hourly={len(hourly_stations)}, MERRA2={len(merra2_stations)}, AOT550={len(aot_stations)}")

    # 创建站点索引
    station_idx = {s: i for i, s in enumerate(hourly_stations)}
    matched = [s for s in stations if s in station_idx]

    # 检查匹配结果
    if not matched:
        print(f"[{timestamp()}] [WARNING] No stations matched for {time_key}")
        return None, (0, 0, 0.0)

    print(f"[{timestamp()}] [INFO] Matched stations: {len(matched)}/{len(stations)}")

    # 初始化结果数组
    sr_results = np.full((len(stations), len(BAND_WAVELENGTHS)), np.nan, dtype=np.float32)
    gen_avail = np.full(len(stations), -1, dtype=np.int8)
    valid_flags = np.zeros(len(stations), dtype=np.int8)
    station_map = {s: i for i, s in enumerate(stations)}

    valid_count = 0
    total_matched = len(matched)

    # 处理匹配的站点
    for station in matched:
        idx = station_idx[station]
        task = (station, idx, hourly, merra2, aot550_data, lucc_dict, station_coords, date)
        _, gen, sr, valid = process_station(task)

        sidx = station_map[station]
        gen_avail[sidx] = gen
        sr_results[sidx] = sr
        valid_flags[sidx] = valid
        valid_count += valid

    # 保存结果
    try:
        os.makedirs(os.path.dirname(paths["output"]), exist_ok=True)
        with nc.Dataset(paths["output"], 'w') as ds:
            ds.createDimension('station', len(stations))

            # 站点变量
            station_var = ds.createVariable('Station', str, ('station',))
            station_var[:] = np.array(stations, dtype=object)

            # 可用性变量
            gen_var = ds.createVariable('General_availability', 'i1', ('station',))
            gen_var[:] = gen_avail

            # 有效性标志
            valid_var = ds.createVariable('valid_flag', 'i1', ('station',))
            valid_var[:] = valid_flags

            # 波段数据
            for i, band in enumerate(BAND_NAMES):
                band_var = ds.createVariable(band, 'f4', ('station',))
                band_var[:] = sr_results[:, i]
                band_var.units = "reflectance"

            # 元数据
            ds.date_created = timestamp()
            ds.title = 'Himawari-8 Surface Reflectance'
            ds.time = hour_str
            ds.date = date_str
            ds.source = "6S atmospheric correction"

        ratio = valid_count / total_matched if total_matched > 0 else 0
        print(f"[{timestamp()}] [SUCCESS] Saved {paths['output']} - Valid: {valid_count}/{total_matched} ({ratio:.1%})")
        return paths["output"], (valid_count, total_matched, ratio)
    except Exception as e:
        print(f"[{timestamp()}] [ERROR] Save failed for {paths['output']}: {str(e)}")
        return None, (0, 0, 0.0)


def load_lucc():
    """加载LUCC数据"""
    try:
        with nc.Dataset(PATHS["lucc"]) as ds:
            stations = [str(s).strip() for s in ds.variables['Station'][:]]
            lucc = ds.variables['LC_type1'][0, :]  # 最新年份数据
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

            # 处理掩码数组
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
    """主处理函数"""
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

    # 并行处理
    processed = []
    total_valid = 0
    total_stations = 0

    with ProcessPoolExecutor(max_workers=min(8, os.cpu_count())) as executor:
        futures = {executor.submit(process_hour, *task): task for task in tasks}

        for future in as_completed(futures):
            date, hour, *_ = futures[future]
            time_key = f"{date.strftime('%Y%m%d')}_{hour * 100:04d}"

            try:
                result, stats = future.result()
                if result:
                    processed.append(result)
                    v, t, _ = stats
                    total_valid += v
                    total_stations += t
            except Exception as e:
                print(f"[{timestamp()}] [ERROR] Task failed for {time_key}: {str(e)}")

    # 最终统计
    hours = (time.time() - start) / 3600
    ratio = total_valid / total_stations if total_stations else 0

    print(f"\n[{timestamp()}] [SUMMARY] Processing completed")
    print(f"  Processed files: {len(processed)}")
    print(f"  Total stations: {total_stations}")
    print(f"  Valid stations: {total_valid} ({ratio:.1%})")
    print(f"  Total time: {hours:.2f} hours")


if __name__ == "__main__":
    main()