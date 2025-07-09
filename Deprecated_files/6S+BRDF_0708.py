import os
import time
import netCDF4 as nc
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
from Py6S import *
from scipy.interpolate import RegularGridInterpolator
import numba as nb
import multiprocessing

# 路径配置
PATHS = {
    "hourly_toa": "D:/H8_data/Hourly_TOA_Angles/",
    "merra2": "D:/H8_data/MERRA2/",
    "merra2_aot550": "D:/H8_data/MERRA2_AOT550/",
    "lucc": "D:/H8_data/LC_2015_2024.nc",
    "output": "D:/H8_Data/H8SR/",
    "luts": "D:/H8_data/LUTs.nc",
    "lut_cache": "D:/H8_data/LUT_Cache/"  # 新增LUT缓存路径
}

# 只保留红色和近红外波段
BAND_WAVELENGTHS = [0.64, 0.86]
BAND_NAMES = [f"Albedo_0{i + 1}" for i in range(2, 4)]  # 只保留波段03和04
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

# LUT配置参数 - 大幅减少网格点数
LUT_PARAMS = {
    'solar_zenith': np.linspace(0, 80, 9),  # 0, 10, 20,...,80 (9个点)
    'view_zenith': np.linspace(0, 70, 8),  # 0, 10, 20,...,70 (8个点)
    'relative_azimuth': np.linspace(0, 180, 10),  # 0, 20, 40,...,180 (10个点)
    'aot550': np.array([0.01, 0.1, 0.3, 0.7]),  # 4个点
    'water': np.array([0.5, 1.0, 3.0, 5.0]),  # 4个点 (g/cm²)
    'ozone': np.array([0.2, 0.4]),  # 2个点 (cm-atm)
    'toa_reflectance': np.linspace(0, 1.0, 11),  # 0, 0.1, 0.2,...,1.0 (11个点)
    'bands': BAND_WAVELENGTHS
}

# 创建LUT缓存目录
os.makedirs(PATHS["lut_cache"], exist_ok=True)


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_lut_key(profile_type, brdf_params):
    """生成LUT的唯一标识键"""
    profile_str = str(profile_type).split('.')[-1]
    brdf_str = "_".join([f"{k}={v}" for k, v in sorted(brdf_params.items())])
    return f"{profile_str}_{brdf_str}"


def create_lut(profile_type, brdf_params):
    """创建查找表(LUT)"""
    lut_key = generate_lut_key(profile_type, brdf_params)
    lut_file = os.path.join(PATHS["lut_cache"], f"{lut_key}.nc")

    # 检查是否已存在缓存
    if os.path.exists(lut_file):
        print(f"[{timestamp()}] [LUT] Loading existing LUT: {lut_key}")
        with nc.Dataset(lut_file) as ds:
            return ds['sr'][:], lut_file

    print(f"[{timestamp()}] [LUT] Generating new LUT: {lut_key}")
    s = SixS()
    s.altitudes.set_sensor_custom_altitude(99)
    s.aero_profile = AeroProfile.PredefinedType(AeroProfile.Continental)
    s.atmos_profile = profile_type

    # 设置BRDF模型
    if brdf_params["model"] == "Rahman":
        s.ground_reflectance = GroundReflectance.HomogeneousRahman(
            brdf_params["intensity"], brdf_params["asymmetry"], brdf_params["structural"])
    elif brdf_params["model"] == "Walthall":
        s.ground_reflectance = GroundReflectance.HomogeneousWalthall(
            brdf_params["param1"], brdf_params["param2"], brdf_params["param3"], brdf_params["albedo"])
    else:
        s.ground_reflectance = GroundReflectance.HomogeneousLambertian(brdf_params["albedo"])

    # 创建LUT数组 [sz, vz, az, aot, water, ozone, toa, band]
    lut_shape = (
        len(LUT_PARAMS['solar_zenith']),
        len(LUT_PARAMS['view_zenith']),
        len(LUT_PARAMS['relative_azimuth']),
        len(LUT_PARAMS['aot550']),
        len(LUT_PARAMS['water']),
        len(LUT_PARAMS['ozone']),
        len(LUT_PARAMS['toa_reflectance']),
        len(LUT_PARAMS['bands'])
    )
    lut_data = np.zeros(lut_shape, dtype=np.float32)

    total_points = np.prod(lut_shape[:-1])
    processed = 0
    start_time = time.time()
    last_percent = -1

    # 计算总波段数
    num_bands = len(LUT_PARAMS['bands'])

    # 获取参数数组长度
    sz_len = len(LUT_PARAMS['solar_zenith'])
    vz_len = len(LUT_PARAMS['view_zenith'])
    az_len = len(LUT_PARAMS['relative_azimuth'])
    aot_len = len(LUT_PARAMS['aot550'])
    w_len = len(LUT_PARAMS['water'])
    o_len = len(LUT_PARAMS['ozone'])
    toa_len = len(LUT_PARAMS['toa_reflectance'])

    # 遍历所有参数组合
    for i_sz in range(sz_len):
        sz = LUT_PARAMS['solar_zenith'][i_sz]
        for i_vz in range(vz_len):
            vz = LUT_PARAMS['view_zenith'][i_vz]
            for i_az in range(az_len):
                az = LUT_PARAMS['relative_azimuth'][i_az]

                # 设置几何参数
                s.geometry = Geometry.User()
                s.geometry.solar_z = sz
                s.geometry.view_z = vz
                s.geometry.relative_azimuth = az

                for i_aot in range(aot_len):
                    aot = LUT_PARAMS['aot550'][i_aot]
                    s.aot550 = aot

                    for i_w in range(w_len):
                        water = LUT_PARAMS['water'][i_w]
                        for i_o in range(o_len):
                            ozone = LUT_PARAMS['ozone'][i_o]
                            s.atmos_profile = AtmosProfile.UserWaterAndOzone(water, ozone)

                            for i_toa in range(toa_len):
                                toa = LUT_PARAMS['toa_reflectance'][i_toa]
                                s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(toa)

                                # 一次性处理所有波段
                                band_results = []
                                for band in LUT_PARAMS['bands']:
                                    s.wavelength = Wavelength(band)
                                    try:
                                        s.run()
                                        band_results.append(s.outputs.pixel_reflectance)
                                    except:
                                        band_results.append(np.nan)

                                # 存储所有波段结果
                                for i_b, result in enumerate(band_results):
                                    lut_data[i_sz, i_vz, i_az, i_aot, i_w, i_o, i_toa, i_b] = result

                                # 更新进度
                                processed += num_bands
                                current_percent = int(processed / total_points * 100)
                                if current_percent > last_percent:
                                    last_percent = current_percent
                                    elapsed = time.time() - start_time
                                    # 估计剩余时间
                                    remaining = (total_points - processed) * (
                                            elapsed / processed) if processed > 0 else 0
                                    print(f"[{timestamp()}] [LUT] Progress: {current_percent}% "
                                          f"({processed}/{total_points}) - Elapsed: {elapsed:.0f}s, "
                                          f"Remaining: {remaining:.0f}s")

    # 保存LUT
    with nc.Dataset(lut_file, 'w') as ds:
        ds.createDimension('solar_zenith', len(LUT_PARAMS['solar_zenith']))
        ds.createDimension('view_zenith', len(LUT_PARAMS['view_zenith']))
        ds.createDimension('relative_azimuth', len(LUT_PARAMS['relative_azimuth']))
        ds.createDimension('aot550', len(LUT_PARAMS['aot550']))
        ds.createDimension('water', len(LUT_PARAMS['water']))
        ds.createDimension('ozone', len(LUT_PARAMS['ozone']))
        ds.createDimension('toa_reflectance', len(LUT_PARAMS['toa_reflectance']))
        ds.createDimension('band', len(LUT_PARAMS['bands']))

        sz_var = ds.createVariable('solar_zenith', 'f4', ('solar_zenith',))
        sz_var[:] = LUT_PARAMS['solar_zenith']

        vz_var = ds.createVariable('view_zenith', 'f4', ('view_zenith',))
        vz_var[:] = LUT_PARAMS['view_zenith']

        az_var = ds.createVariable('relative_azimuth', 'f4', ('relative_azimuth',))
        az_var[:] = LUT_PARAMS['relative_azimuth']

        aot_var = ds.createVariable('aot550', 'f4', ('aot550',))
        aot_var[:] = LUT_PARAMS['aot550']

        w_var = ds.createVariable('water', 'f4', ('water',))
        w_var[:] = LUT_PARAMS['water']

        o_var = ds.createVariable('ozone', 'f4', ('ozone',))
        o_var[:] = LUT_PARAMS['ozone']

        toa_var = ds.createVariable('toa_reflectance', 'f4', ('toa_reflectance',))
        toa_var[:] = LUT_PARAMS['toa_reflectance']

        band_var = ds.createVariable('band', 'f4', ('band',))
        band_var[:] = LUT_PARAMS['bands']

        sr_var = ds.createVariable('sr', 'f4', ('solar_zenith', 'view_zenith', 'relative_azimuth',
                                                'aot550', 'water', 'ozone', 'toa_reflectance', 'band'))
        sr_var[:] = lut_data

    print(f"[{timestamp()}] [LUT] Saved LUT: {lut_file}")
    return lut_data, lut_file


def get_brdf_params(lucc_value):
    """获取BRDF参数"""
    try:
        lucc_int = int(lucc_value)
        return LUCC_TO_BRDF.get(lucc_int, LUCC_TO_BRDF[255])
    except (ValueError, TypeError):
        return LUCC_TO_BRDF[255]


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


def convert_merra2_units(to3, tqv):
    """转换MERRA2单位"""
    if np.isnan(to3) or np.isnan(tqv):
        return np.nan, np.nan

    return to3 * 0.001, tqv * 0.1  # Dobson->cm-atm, kg/m²->g/cm²


@nb.njit(parallel=True, fastmath=True)
def vectorized_lookup(lut, indices, ranges):
    """使用Numba加速的向量化LUT查询"""
    results = np.zeros((indices.shape[0], lut.shape[-1]), dtype=np.float32)

    for i in nb.prange(indices.shape[0]):
        # 获取当前点的所有维度索引
        idx_tuple = tuple(indices[i, j] for j in range(indices.shape[1]))

        # 检查边界
        valid = True
        for dim in range(len(ranges)):
            if not (0 <= idx_tuple[dim] < ranges[dim]):
                valid = False
                break

        if not valid:
            results[i] = np.nan
            continue

        # 直接获取值
        for band in range(lut.shape[-1]):
            results[i, band] = lut[idx_tuple + (band,)]

    return results


def process_stations_batch(station_batch):
    """处理一批站点 - 使用预计算的LUT"""
    stations, indices, hourly, merra2, aot550_data, lucc_dict, coords, date, luts = station_batch

    # 准备输入数组
    num_stations = len(stations)
    # 只保留两个波段
    input_data = np.zeros((num_stations, 8),
                          dtype=np.float32)  # [sz, vz, az, aot, water, ozone, toa1, toa2]

    # 收集所有需要的数据
    for i, station in enumerate(stations):
        idx = indices[i]
        lat, lon = coords.get(station, (np.nan, np.nan))

        # 获取角度
        saz = hourly['SAZ'][idx] if idx < len(hourly['SAZ']) else np.nan
        saa = hourly['SAA'][idx] if idx < len(hourly['SAA']) else np.nan
        soz = hourly['SOZ'][idx] if idx < len(hourly['SOZ']) else np.nan
        soa = hourly['SOA'][idx] if idx < len(hourly['SOA']) else np.nan

        # 计算相对方位角
        rel_az = abs(saa - soa)
        rel_az = min(rel_az, 360 - rel_az)

        # 获取大气参数
        to3 = merra2['TO3'][idx] if idx < len(merra2['TO3']) else np.nan
        tqv = merra2['TQV'][idx] if idx < len(merra2['TQV']) else np.nan
        ozone, water = convert_merra2_units(to3, tqv)

        # 获取AOT550
        aot550 = aot550_data['AOT550'][idx] if idx < len(aot550_data['AOT550']) else np.nan

        # 获取TOA反射率 (只处理两个波段)
        cos_soz = np.cos(np.radians(soz)) if not np.isnan(soz) else np.nan
        toa_refs = []
        for band in BAND_NAMES:  # 现在只有两个波段
            albedo = hourly[band][idx] if idx < len(hourly[band]) else np.nan
            if np.isnan(albedo) or albedo < 0 or albedo > 1 or np.isnan(cos_soz) or cos_soz <= 0.01:
                toa_refs.append(np.nan)
            else:
                toa_ref = albedo / max(cos_soz, 0.01)
                toa_refs.append(np.clip(toa_ref, 0.0, 1.0))

        # 填充输入数组
        input_data[i, 0] = soz
        input_data[i, 1] = saz
        input_data[i, 2] = rel_az
        input_data[i, 3] = aot550
        input_data[i, 4] = water
        input_data[i, 5] = ozone
        input_data[i, 6:8] = toa_refs  # 只保留两个波段

    # 准备结果数组
    sr_results = np.full((num_stations, len(BAND_WAVELENGTHS)), np.nan, dtype=np.float32)  # 两个波段
    gen_avail = np.full(num_stations, -1, dtype=np.int8)
    valid_flags = np.zeros(num_stations, dtype=np.int8)

    # 按BRDF类型分组处理
    brdf_groups = {}
    for i, station in enumerate(stations):
        lucc_value = lucc_dict.get(station, 255)
        brdf_params = get_brdf_params(lucc_value)
        brdf_key = generate_lut_key(get_atmos_profile(coords[station][0], date), brdf_params)

        if brdf_key not in brdf_groups:
            brdf_groups[brdf_key] = []
        brdf_groups[brdf_key].append(i)

    # 对每个BRDF组进行处理
    for brdf_key, indices_list in brdf_groups.items():
        if brdf_key not in luts:
            print(f"[{timestamp()}] [WARNING] LUT not found for {brdf_key}")
            continue

        lut_data = luts[brdf_key]
        group_data = input_data[indices_list]

        # 计算每个维度的索引
        dim_indices = np.zeros((len(indices_list), 7), dtype=np.int32)
        dim_ranges = [
            len(LUT_PARAMS['solar_zenith']),
            len(LUT_PARAMS['view_zenith']),
            len(LUT_PARAMS['relative_azimuth']),
            len(LUT_PARAMS['aot550']),
            len(LUT_PARAMS['water']),
            len(LUT_PARAMS['ozone']),
            len(LUT_PARAMS['toa_reflectance'])
        ]

        # 计算每个参数的索引
        dim_indices[:, 0] = np.digitize(group_data[:, 0], LUT_PARAMS['solar_zenith']) - 1
        dim_indices[:, 1] = np.digitize(group_data[:, 1], LUT_PARAMS['view_zenith']) - 1
        dim_indices[:, 2] = np.digitize(group_data[:, 2], LUT_PARAMS['relative_azimuth']) - 1
        dim_indices[:, 3] = np.digitize(group_data[:, 3], LUT_PARAMS['aot550']) - 1
        dim_indices[:, 4] = np.digitize(group_data[:, 4], LUT_PARAMS['water']) - 1
        dim_indices[:, 5] = np.digitize(group_data[:, 5], LUT_PARAMS['ozone']) - 1

        # 对每个波段分别处理TOA反射率
        for band_idx in range(len(BAND_WAVELENGTHS)):
            dim_indices[:, 6] = np.digitize(group_data[:, 6 + band_idx], LUT_PARAMS['toa_reflectance']) - 1
            band_results = vectorized_lookup(lut_data, dim_indices, np.array(dim_ranges))

            # 更新结果
            for j, idx in enumerate(indices_list):
                sr_results[idx, band_idx] = band_results[j, band_idx]
                if not np.isnan(band_results[j, band_idx]):
                    valid_flags[idx] = 1

    # 设置可用性标志
    for i in range(num_stations):
        if np.any(np.isnan(input_data[i, :6])):  # 检查输入参数是否有效
            gen_avail[i] = 1
        else:
            gen_avail[i] = 0

    return stations, gen_avail, sr_results, valid_flags


def get_atmos_profile(lat, date):
    """根据纬度和日期获取大气廓线"""
    if np.isnan(lat):
        return AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)

    for (low, high), profile in LATITUDE_TO_PROFILE.items():
        if low <= lat < high:
            if isinstance(profile, dict):
                month_group = 5 if date.month in range(5, 10) else 9
                return profile[month_group]
            else:
                return profile

    return AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)


def create_lut_wrapper(args):
    """包装函数用于多进程生成LUT"""
    profile, brdf_params = args
    lut_key = generate_lut_key(profile, brdf_params)
    lut_file = os.path.join(PATHS["lut_cache"], f"{lut_key}.nc")

    # 检查是否已存在缓存
    if os.path.exists(lut_file):
        print(f"[{timestamp()}] [LUT] Loading existing LUT: {lut_key}")
        with nc.Dataset(lut_file) as ds:
            return lut_key, ds['sr'][:]

    print(f"[{timestamp()}] [LUT] Generating LUT for {lut_key}")
    lut_data, _ = create_lut(profile, brdf_params)
    return lut_key, lut_data


def preload_luts(lucc_dict):
    """预加载所有需要的LUTs - 使用多进程并行生成"""
    print(f"[{timestamp()}] [LUT] Preloading LUTs using multiprocessing...")
    luts = {}

    # 获取实际存在的LUCC值
    existing_lucc = set(lucc_dict.values())
    print(f"[{timestamp()}] [LUT] Found {len(existing_lucc)} unique LUCC types in station data")

    # 获取所有可能的大气廓线
    unique_profiles = set()
    for profile_dict in LATITUDE_TO_PROFILE.values():
        if isinstance(profile_dict, dict):
            for prof in profile_dict.values():
                unique_profiles.add(prof)
        else:
            unique_profiles.add(profile_dict)
    print(f"[{timestamp()}] [LUT] Found {len(unique_profiles)} unique atmospheric profiles")

    # 准备任务参数
    tasks = []
    for lucc_value in existing_lucc:
        brdf_params = get_brdf_params(lucc_value)
        for profile in unique_profiles:
            tasks.append((profile, brdf_params))

    print(f"[{timestamp()}] [LUT] Generating {len(tasks)} LUTs with {multiprocessing.cpu_count()} processes")

    # 使用进程池并行生成LUT
    with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
        futures = [executor.submit(create_lut_wrapper, task) for task in tasks]

        for i, future in enumerate(as_completed(futures)):
            try:
                lut_key, lut_data = future.result()
                luts[lut_key] = lut_data
                print(f"[{timestamp()}] [LUT] [{i + 1}/{len(tasks)}] Loaded/generated LUT: {lut_key}")
            except Exception as e:
                print(f"[{timestamp()}] [ERROR] LUT generation failed: {str(e)}")

    print(f"[{timestamp()}] [LUT] Loaded {len(luts)} LUTs")
    return luts


def process_hour(date, hour, stations, lucc_dict, station_coords, luts):
    """处理单小时数据"""
    date_str = date.strftime("%Y%m%d")
    hour_str = f"{hour * 100:04d}"
    time_key = f"{date_str}_{hour_str}"

    # 文件路径
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
    hourly = load_netcdf(paths["toa"], ['Station'] + BAND_NAMES + ANGLE_NAMES + ['hourly_availability'])
    merra2 = load_netcdf(paths["merra"], ['Station', 'TO3', 'TQV'])
    aot550_data = load_netcdf(paths["aot550"], ['Station', 'AOT550'])

    if None in [hourly, merra2, aot550_data]:
        print(f"[{timestamp()}] [ERROR] Data load failed for {time_key}")
        return None, (0, 0, 0.0)

    # 检查站点匹配
    hourly_stations = hourly.get('Station', [])
    station_idx = {s: i for i, s in enumerate(hourly_stations)}
    matched = [s for s in stations if s in station_idx]

    if not matched:
        print(f"[{timestamp()}] [WARNING] No stations matched for {time_key}")
        return None, (0, 0, 0.0)

    # 分批处理站点 (每批100个站点)
    batch_size = 100
    num_batches = (len(matched) + batch_size - 1) // batch_size

    # 初始化结果数组
    sr_results = np.full((len(stations), len(BAND_WAVELENGTHS)), np.nan, dtype=np.float32)
    gen_avail = np.full(len(stations), -1, dtype=np.int8)
    valid_flags = np.zeros(len(stations), dtype=np.int8)
    station_map = {s: i for i, s in enumerate(stations)}

    valid_count = 0
    total_matched = len(matched)

    # 处理所有批次
    for i in range(num_batches):
        start_idx = i * batch_size
        end_idx = min((i + 1) * batch_size, len(matched))
        batch_stations = matched[start_idx:end_idx]
        batch_indices = [station_idx[s] for s in batch_stations]

        batch_data = (
            batch_stations,
            batch_indices,
            hourly,
            merra2,
            aot550_data,
            lucc_dict,
            station_coords,
            date,
            luts
        )

        batch_stations, batch_gen, batch_sr, batch_valid = process_stations_batch(batch_data)

        # 更新结果
        for s, gen, sr, valid in zip(batch_stations, batch_gen, batch_sr, batch_valid):
            sidx = station_map[s]
            gen_avail[sidx] = gen
            sr_results[sidx] = sr
            valid_flags[sidx] = valid
            if valid:
                valid_count += 1

    # 保存结果
    try:
        os.makedirs(os.path.dirname(paths["output"]), exist_ok=True)
        with nc.Dataset(paths["output"], 'w') as ds:
            ds.createDimension('station', len(stations))

            station_var = ds.createVariable('Station', str, ('station',))
            station_var[:] = np.array(stations, dtype=object)

            gen_var = ds.createVariable('General_availability', 'i1', ('station',))
            gen_var[:] = gen_avail

            valid_var = ds.createVariable('valid_flag', 'i1', ('station',))
            valid_var[:] = valid_flags

            for i, band in enumerate(BAND_NAMES):
                band_var = ds.createVariable(band, 'f4', ('station',))
                band_var[:] = sr_results[:, i]
                band_var.units = "reflectance"

            ds.date_created = timestamp()
            ds.title = 'Himawari-8 Surface Reflectance'
            ds.time = hour_str
            ds.date = date_str
            ds.source = "6S atmospheric correction with LUT"

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
    station_coords = load_coords()
    if not station_coords:
        print(f"[{timestamp()}] [ERROR] No station coordinates")
        return

    stations = list(station_coords.keys())

    lucc_dict = load_lucc()
    if not lucc_dict:
        print(f"[{timestamp()}] [ERROR] No LUCC data")
        return

    # 预加载所有LUTs - 使用多进程并行生成
    luts = preload_luts(lucc_dict)
    if not luts:
        print(f"[{timestamp()}] [ERROR] No LUTs loaded")
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
            tasks.append((date, hour, stations, lucc_dict, station_coords, luts))

    print(f"[{timestamp()}] [INFO] Total tasks: {len(tasks)}")

    # 并行处理
    processed = []
    total_valid = 0
    total_stations = 0

    # 根据任务数量调整进程数
    num_workers = min(8, len(tasks), os.cpu_count())
    print(f"[{timestamp()}] [INFO] Using {num_workers} workers")

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(process_hour, *task): task for task in tasks}

        for future in as_completed(futures):
            task = futures[future]
            date, hour, *_ = task
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