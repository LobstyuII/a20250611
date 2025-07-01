import os
import time
import netCDF4 as nc
import numpy as np
from datetime import datetime
from Py6S import *

# 更新路径配置
PATHS = {
    "hourly_toa": "D:/H8_data/Hourly_TOA_Angles/",
    "merra2": "D:/H8_data/MERRA2/",
    "lucc": "D:/H8_data/LC_2015_2024.nc",
    "output": "D:/H8_Data/H8SR/",
    "luts": "D:/H8_data/LUTs.nc",
    "aod": "D:/H8_data/H8L3ARP/"
}

# 只使用前4个波段
BAND_WAVELENGTHS = [0.47, 0.51, 0.64, 0.86]
BAND_NAMES = [f"Albedo_0{i + 1}" for i in range(0, 4)]
ANGLE_NAMES = ['SAZ', 'SAA', 'SOZ', 'SOA']

# LUCC到BRDF参数的映射
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

# 预初始化6S对象
PRECONFIGURED_SIXS = None


def initialize_sixs():
    """初始化6S对象"""
    global PRECONFIGURED_SIXS

    if PRECONFIGURED_SIXS is None:
        PRECONFIGURED_SIXS = SixS()


def get_current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def calculate_data_validity(data_array):
    """计算数据有效性比例"""
    if data_array.size == 0:
        return 0, 0, 0.0
    total = data_array.size
    valid = np.count_nonzero(~np.isnan(data_array))
    return valid, total, valid / total if total > 0 else 0.0


def load_netcdf_data(file_path, variables, step_name=""):
    """高效加载NetCDF文件数据，处理掩码值，并计算有效性"""
    if not os.path.exists(file_path):
        print(f"[{get_current_timestamp()}] [STEP:{step_name}] File not found: {file_path}")
        return None, (0, 0, 0.0)

    try:
        with nc.Dataset(file_path) as ds:
            data = {}
            validity_info = {}

            for var in variables:
                if var == 'Station':
                    var_data = ds.variables[var][:]
                    # 处理不同格式的站点数据
                    if var_data.dtype.kind == 'S':  # 字节字符串
                        data[var] = [s.tobytes().decode('utf-8').strip() for s in var_data]
                    elif var_data.dtype.kind == 'U':  # Unicode字符串
                        data[var] = [s.strip() for s in var_data]
                    else:  # 其他类型
                        data[var] = [str(s).strip() for s in var_data]
                    # 字符串数据不计算有效性
                    validity_info[var] = (len(data[var]), len(data[var]), 1.0)
                else:
                    var_data = ds.variables[var][:]
                    if isinstance(var_data, np.ma.MaskedArray):
                        var_data = var_data.filled(np.nan)
                    data[var] = var_data
                    # 计算数值数据的有效性
                    valid, total, ratio = calculate_data_validity(var_data)
                    validity_info[var] = (valid, total, ratio)

            return data, validity_info
    except Exception as e:
        print(f"[{get_current_timestamp()}] [STEP:{step_name}] Error loading {file_path}: {str(e)}")
        return None, (0, 0, 0.0)


def set_brdf_model(s, lucc_value):
    """根据LUCC类型设置BRDF模型"""
    brdf_params = LUCC_TO_BRDF.get(int(lucc_value), LUCC_TO_BRDF[255])

    if brdf_params["model"] == "Rahman":
        s.ground_reflectance = GroundReflectance.HomogeneousRahman(
            intensity=brdf_params["intensity"],
            asymmetry_factor=brdf_params["asymmetry"],
            structural_parameter=brdf_params["structural"]
        )
    elif brdf_params["model"] == "Walthall":
        s.ground_reflectance = GroundReflectance.HomogeneousWalthall(
            param1=brdf_params["param1"],
            param2=brdf_params["param2"],
            param3=brdf_params["param3"],
            albedo=brdf_params["albedo"]
        )
    else:
        s.ground_reflectance = GroundReflectance.HomogeneousLambertian(brdf_params["albedo"])
    return s


def calculate_general_availability(hourly_avail):
    """根据小时可用性标志确定综合可用性"""
    return 1 if hourly_avail != 0 else 0


def convert_merra2_units(to3, tqv):
    """转换MERRA2单位到Py6S所需单位，处理NaN值"""
    if np.isnan(to3) or np.isnan(tqv):
        return np.nan, np.nan

    ozone_cmatm = to3 * 0.001  # Dobson -> cm-atm
    water_gcm2 = tqv * 0.1  # kg/m² -> g/cm²
    return ozone_cmatm, water_gcm2


def convert_aot500_to_aot550(aot500, angstrom_exponent=1.3):
    """将500nm AOT转换为550nm AOT"""
    if np.isnan(aot500) or aot500 < 0:
        return np.nan
    return aot500 * (500 / 550) ** angstrom_exponent


def process_station(station_data):
    """处理单个站点的数据"""
    station, idx, hourly_data, merra2_data, aod_data, lucc_dict, station_coords, date = station_data
    lat, lon = station_coords.get(station, (np.nan, np.nan))

    # 计算综合可用性
    hourly_avail = hourly_data['hourly_availability'][idx]
    gen_avail = calculate_general_availability(hourly_avail)

    if gen_avail == 1:
        return station, gen_avail, np.full(len(BAND_WAVELENGTHS), np.nan), 0

    # 获取大气参数并转换单位 - 添加边界检查
    to3 = merra2_data['TO3'][idx] if 'TO3' in merra2_data and idx < len(merra2_data['TO3']) else np.nan
    tqv = merra2_data['TQV'][idx] if 'TQV' in merra2_data and idx < len(merra2_data['TQV']) else np.nan
    ozone_cmatm, water_gcm2 = convert_merra2_units(to3, tqv)

    # 获取AOD数据 - 添加边界检查
    aot500 = aod_data['AOT'][idx] if 'AOT' in aod_data and idx < len(aod_data['AOT']) else np.nan
    data_avail = aod_data['Data_Availability'][idx] if 'Data_Availability' in aod_data and idx < len(
        aod_data['Data_Availability']) else 1
    aot550 = convert_aot500_to_aot550(aot500) if data_avail == 0 and not np.isnan(aot500) and aot500 >= 0 else np.nan

    # 获取TOA反射率和角度 - 添加边界检查
    toa_reflectances = []
    for band in BAND_NAMES:
        if band in hourly_data and idx < len(hourly_data[band]):
            toa_reflectances.append(hourly_data[band][idx])
        else:
            toa_reflectances.append(np.nan)

    # 获取角度数据 - 添加边界检查
    saz = hourly_data['SAZ'][idx] if 'SAZ' in hourly_data and idx < len(hourly_data['SAZ']) else np.nan
    saa = hourly_data['SAA'][idx] if 'SAA' in hourly_data and idx < len(hourly_data['SAA']) else np.nan
    soz = hourly_data['SOZ'][idx] if 'SOZ' in hourly_data and idx < len(hourly_data['SOZ']) else np.nan
    soa = hourly_data['SOA'][idx] if 'SOA' in hourly_data and idx < len(hourly_data['SOA']) else np.nan

    # 获取LUCC类型
    lucc_value = lucc_dict.get(station, 255)

    # 执行6S大气校正+BRDF归一化
    sr_results = np.full(len(BAND_WAVELENGTHS), np.nan, dtype=np.float32)
    valid_flag = 0

    try:
        # 复用预初始化的6S对象
        s = SixS()
        s.geometry = Geometry.User()

        # 设置几何参数
        s.geometry.solar_z = soz
        s.geometry.solar_a = soa
        s.geometry.view_z = saz
        s.geometry.view_a = saa

        # 设置大气参数
        if not np.isnan(water_gcm2) and not np.isnan(ozone_cmatm) and water_gcm2 > 0 and ozone_cmatm > 0:
            s.atmos_profile = AtmosProfile.UserWaterAndOzone(water=water_gcm2, ozone=ozone_cmatm)
        elif not np.isnan(lat):
            # 根据纬度选择最近的大气廓线
            if -30 <= lat <= 30:
                s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.Tropical)
            elif 30 < lat <= 60:
                if date.month in [5, 6, 7, 8, 9]:
                    s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)
                else:
                    s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeWinter)
            else:
                if date.month in [5, 6, 7, 8, 9]:
                    s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.SubarcticSummer)
                else:
                    s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.SubarcticWinter)
        else:
            s.atmos_profile = AtmosProfile.PredefinedType(AtmosProfile.MidlatitudeSummer)

        # 设置气溶胶参数
        s.aero_profile = AeroProfile.PredefinedType(AeroProfile.Continental)
        if not np.isnan(aot550) and aot550 >= 0:
            s.aot550 = aot550

        # 设置BRDF模型
        s = set_brdf_model(s, lucc_value)

        # 处理每个波段（只处理前4个波段）
        for band_idx, (wavelength, toa_refl) in enumerate(zip(BAND_WAVELENGTHS, toa_reflectances)):
            if np.isnan(toa_refl) or toa_refl < 0 or toa_refl > 1:
                continue

            try:
                s.wavelength = Wavelength(wavelength)
                s.atmos_corr = AtmosCorr.AtmosCorrBRDFFromReflectance(reflectance=toa_refl)
                s.run()
                sr_results[band_idx] = s.outputs.pixel_reflectance
            except Exception as e:
                print(
                    f"[{get_current_timestamp()}] Error processing band {BAND_NAMES[band_idx]} for station {station}: {str(e)}")
                sr_results[band_idx] = np.nan

        valid_flag = 1
    except Exception as e:
        print(f"[{get_current_timestamp()}] Error processing station {station}: {str(e)}")
        pass

    return station, gen_avail, sr_results, valid_flag


def process_hour(date, hour, stations_list, lucc_dict, station_coords):
    """处理单个小时的数据"""
    date_str = date.strftime("%Y%m%d")
    # 修正时间格式：将小时乘以100得到正确的格式（0000, 1000, 2000等）
    hour_str = f"{hour * 100:04d}"  # 修正时间格式

    print(f"\n[{get_current_timestamp()}] [STEP:START] Processing {date_str}_{hour_str} ================")

    # 构建文件路径 - 使用修正后的时间格式
    hourly_toa_file = os.path.join(PATHS["hourly_toa"], date_str[:4], date_str[4:6],
                                   f"H8_hourly_TOA_angles_{date_str}_{hour_str}.nc")
    merra2_file = os.path.join(PATHS["merra2"], date_str[:4], date_str[4:6],
                               f"MERRA2_{date_str}_{hour_str}_TO3_TQV.nc")
    aod_file = os.path.join(PATHS["aod"], date_str[:4], date_str[4:6], f"H8L3ARP_{date_str}_{hour_str}.nc")
    output_file = os.path.join(PATHS["output"], f"SR_{date_str}_{hour_str}.nc")

    # 步骤1: 检查输入文件
    step_name = "FILE_CHECK"
    files_exist = [os.path.exists(hourly_toa_file), os.path.exists(merra2_file), os.path.exists(aod_file)]
    exist_ratio = sum(files_exist) / len(files_exist)
    print(f"[{get_current_timestamp()}] [STEP:{step_name}] File existence ratio: {exist_ratio:.2%} "
          f"(Hourly_TOA: {'Found' if files_exist[0] else 'Missing'}, "
          f"MERRA2: {'Found' if files_exist[1] else 'Missing'}, "
          f"AOD: {'Found' if files_exist[2] else 'Missing'})")

    if not all(files_exist):
        print(f"[{get_current_timestamp()}] [STEP:END] Skipping {date_str}_{hour_str} due to missing files")
        return None, (0, 0, 0.0)

    # 步骤2: 加载数据
    step_name = "DATA_LOAD"
    hourly_data, hourly_validity = load_netcdf_data(hourly_toa_file,
                                                    ['Station'] + BAND_NAMES + ANGLE_NAMES + ['hourly_availability'],
                                                    step_name)
    merra2_data, merra2_validity = load_netcdf_data(merra2_file, ['Station', 'TO3', 'TQV'], step_name)
    aod_data, aod_validity = load_netcdf_data(aod_file, ['Station', 'AOT', 'Data_Availability'], step_name)

    # 打印加载数据的有效性
    def print_validity_info(data_name, validity_dict):
        print(f"[{get_current_timestamp()}] [STEP:{step_name}] {data_name} data validity:")
        for var, (valid, total, ratio) in validity_dict.items():
            print(f"  - {var}: {valid}/{total} ({ratio:.2%})")

    if hourly_data:
        print_validity_info("Hourly_TOA", hourly_validity)
    if merra2_data:
        print_validity_info("MERRA2", merra2_validity)
    if aod_data:
        print_validity_info("AOD", aod_validity)

    if None in [hourly_data, merra2_data, aod_data]:
        print(f"[{get_current_timestamp()}] [STEP:END] Failed to load data for {date_str}_{hour_str}")
        return None, (0, 0, 0.0)

    # 步骤3: 创建站点索引映射
    step_name = "STATION_MAPPING"
    station_idx_map = {station: idx for idx, station in enumerate(hourly_data['Station'])}
    matched_stations = [s for s in stations_list if s in station_idx_map]
    match_ratio = len(matched_stations) / len(stations_list) if stations_list else 0
    print(f"[{get_current_timestamp()}] [STEP:{step_name}] Station match ratio: {match_ratio:.2%} "
          f"({len(matched_stations)}/{len(stations_list)} stations)")

    # 步骤4: 处理站点数据
    step_name = "STATION_PROCESSING"
    print(f"[{get_current_timestamp()}] [STEP:{step_name}] Processing {len(matched_stations)} stations...")

    # 初始化结果数组
    sr_results = np.full((len(stations_list), len(BAND_WAVELENGTHS)), np.nan, dtype=np.float32)
    gen_avail = np.full(len(stations_list), -1, dtype=np.int8)
    valid_flags = np.zeros(len(stations_list), dtype=np.int8)
    station_index_map = {station: idx for idx, station in enumerate(stations_list)}

    valid_count = 0
    total_stations = len(matched_stations)

    for station in matched_stations:
        idx = station_idx_map[station]
        task = (station, idx, hourly_data, merra2_data, aod_data, lucc_dict, station_coords, date)
        station, gen, sr, valid = process_station(task)

        if station in station_index_map:
            sidx = station_index_map[station]
            gen_avail[sidx] = gen
            sr_results[sidx] = sr
            valid_flags[sidx] = valid
            if valid == 1:
                valid_count += 1

    # 计算有效性比例
    sr_validity = []
    for band_idx in range(len(BAND_WAVELENGTHS)):
        band_data = sr_results[:, band_idx]
        valid, total, ratio = calculate_data_validity(band_data)
        sr_validity.append((valid, total, ratio))

    overall_valid_ratio = valid_count / total_stations if total_stations > 0 else 0
    print(f"[{get_current_timestamp()}] [STEP:{step_name}] Station processing completed: "
          f"{valid_count}/{total_stations} stations valid ({overall_valid_ratio:.2%})")

    # 打印各波段有效性
    for band_idx, (valid, total, ratio) in enumerate(sr_validity):
        print(f"  - Band {BAND_NAMES[band_idx]} ({BAND_WAVELENGTHS[band_idx]}μm): "
              f"{valid}/{total} valid ({ratio:.2%})")

    # 步骤5: 保存结果 - 修正为每个波段一个变量
    step_name = "SAVE_RESULTS"
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with nc.Dataset(output_file, 'w') as ds:
            # 创建维度
            ds.createDimension('station', len(stations_list))

            # 创建站点变量 - 修正为 'Station'（大写）
            station_var = ds.createVariable('Station', str, ('station',))
            station_var[:] = np.array(stations_list, dtype=object)

            # 创建可用性变量
            gen_avail_var = ds.createVariable('General_availability', np.int8, ('station',))
            gen_avail_var[:] = gen_avail

            # 创建有效性标志变量
            valid_var = ds.createVariable('valid_flag', np.int8, ('station',))
            valid_var[:] = valid_flags

            # 创建每个波段作为单独的变量（只前4个波段）
            for band_idx, band_name in enumerate(BAND_NAMES):
                band_var = ds.createVariable(band_name, np.float32, ('station',))
                band_var[:] = sr_results[:, band_idx]
                band_var.units = "reflectance"
                band_var.description = f"Surface reflectance for band {band_name} ({BAND_WAVELENGTHS[band_idx]}μm)"

            # 添加全局属性
            ds.date_created = get_current_timestamp()
            ds.title = 'Himawari-8 Surface Reflectance Product'
            ds.time = hour_str
            ds.date = date_str
            ds.source = "6S atmospheric correction with BRDF normalization"
            ds.author = "H8SR Processing System"

        print(f"[{get_current_timestamp()}] [STEP:{step_name}] Generated SR product: {output_file}")
        print(
            f"  Output file structure: Station, General_availability, valid_flag, and separate variables for each band")
        return output_file, (valid_count, total_stations, overall_valid_ratio)
    except Exception as e:
        print(f"[{get_current_timestamp()}] [STEP:{step_name}] Error saving {output_file}: {str(e)}")
        return None, (0, 0, 0.0)


def load_lucc_data():
    """加载LUCC数据到内存"""
    lucc_file = PATHS["lucc"]
    step_name = "LUCC_LOAD"
    if not os.path.exists(lucc_file):
        print(f"[{get_current_timestamp()}] [STEP:{step_name}] LUCC file not found: {lucc_file}")
        return None

    try:
        with nc.Dataset(lucc_file) as ds:
            # 使用正确的变量名 'Station'（大写）
            station_var = ds.variables['Station']
            station_data = station_var[:]
            # 处理不同格式的站点数据
            if station_data.dtype.kind == 'S':  # 字节字符串
                stations = [s.tobytes().decode('utf-8').strip() for s in station_data]
            elif station_data.dtype.kind == 'U':  # Unicode字符串
                stations = [s.strip() for s in station_data]
            else:  # 其他类型
                stations = [str(s).strip() for s in station_data]

            lucc_values = ds.variables['LC_type1'][-1, :]  # 使用最新年份的数据

            if isinstance(lucc_values, np.ma.MaskedArray):
                lucc_values = lucc_values.filled(255)

            # 计算有效性
            valid, total, ratio = calculate_data_validity(lucc_values)
            print(f"[{get_current_timestamp()}] [STEP:{step_name}] LUCC data loaded: "
                  f"{valid}/{total} valid values ({ratio:.2%})")

            return dict(zip(stations, lucc_values))
    except Exception as e:
        print(f"[{get_current_timestamp()}] [STEP:{step_name}] Error loading LUCC data: {str(e)}")
        return None


def load_station_coords():
    """从LUTs.nc文件加载站点经纬度信息"""
    luts_file = PATHS["luts"]
    step_name = "COORDS_LOAD"
    if not os.path.exists(luts_file):
        print(f"[{get_current_timestamp()}] [STEP:{step_name}] LUTs file not found: {luts_file}")
        return {}

    try:
        with nc.Dataset(luts_file) as ds:
            # 使用正确的变量名 'Station'（大写）
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

            # 计算有效性
            lat_valid = np.count_nonzero(~np.isnan(lats))
            lon_valid = np.count_nonzero(~np.isnan(lons))
            total = len(lats)

            print(f"[{get_current_timestamp()}] [STEP:{step_name}] Station coordinates loaded: "
                  f"Lat: {lat_valid}/{total} valid, Lon: {lon_valid}/{total} valid")

            return {station: (lat, lon) for station, lat, lon in zip(stations, lats, lons)}
    except Exception as e:
        print(f"[{get_current_timestamp()}] [STEP:{step_name}] Error loading station coordinates: {str(e)}")
        return {}


def test_main():
    """单线程测试函数，处理3个指定时间点"""
    start_time = time.time()
    initialize_sixs()  # 初始化6S对象

    # 创建输出目录
    os.makedirs(PATHS["output"], exist_ok=True)

    # 步骤1: 加载站点坐标
    step_name = "INIT_COORDS"
    print(f"[{get_current_timestamp()}] [STEP:{step_name}] Loading station coordinates...")
    station_coords = load_station_coords()
    if not station_coords:
        print(f"[{get_current_timestamp()}] [STEP:{step_name}] Failed to load station coordinates. Exiting.")
        return
    stations_list = list(station_coords.keys())
    print(f"[{get_current_timestamp()}] [STEP:{step_name}] Loaded {len(stations_list)} stations")

    # 步骤2: 加载LUCC数据
    step_name = "INIT_LUCC"
    print(f"[{get_current_timestamp()}] [STEP:{step_name}] Loading LUCC data...")
    lucc_dict = load_lucc_data()
    if lucc_dict is None:
        print(f"[{get_current_timestamp()}] [STEP:{step_name}] Failed to load LUCC data. Exiting.")
        return

    # 处理3个指定时间点 (2015-07-07 的 00:00, 10:00, 20:00)
    target_date = datetime(2015, 7, 7)
    target_hours = [0, 10, 20]

    total_valid = 0
    total_stations = 0
    processed_files = []

    for hour in target_hours:
        print(f"[{get_current_timestamp()}] Processing hour: {hour:02d}00")
        output_file, (valid, total, ratio) = process_hour(target_date, hour, stations_list, lucc_dict, station_coords)
        if output_file:
            processed_files.append(output_file)
            total_valid += valid
            total_stations += total

    # 最终统计
    step_name = "FINAL_STATS"
    total_ratio = total_valid / total_stations if total_stations > 0 else 0
    total_time = time.time() - start_time

    print(f"\n[{get_current_timestamp()}] [STEP:{step_name}] TEST PROCESSING SUMMARY")
    print(f"  Processed {len(processed_files)} time points")
    print(f"  Total stations processed: {total_stations}")
    print(f"  Valid stations: {total_valid} ({total_ratio:.2%})")
    if processed_files:
        print(f"  Generated files: {', '.join(processed_files)}")
    else:
        print("  No files generated")
    print(f"  Total processing time: {total_time:.2f} seconds")


if __name__ == "__main__":
    test_main()