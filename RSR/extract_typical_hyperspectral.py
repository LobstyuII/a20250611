import os
import numpy as np
from netCDF4 import Dataset

# 配置路径
input_dir = r'D:\H8_data\USGS'
output_dir = input_dir

# 定义地表类型与记录号映射
record_mapping = {
    'Evergreen': [1, 2, 5],
    'Deciduous': [3, 4],
    'Grass': [6, 7, 8, 9, 10],
    'Cropland': [12, 14],
    'Urban': [13],
    'Barren': [16]
}

# 定义文件名与记录号映射
file_record_map = {
    's07_ASD_Douglas-Fir_YNP-DF-1_forest_AVIRISb_RTGC': 1,
    's07_ASD_Douglas-Fir_YNP-DF-1_forest_AVIRISb_RTGC': 2,
    's07_ASD_Douglas-Fir_YNP-DF-1_forest_AVIRISb_RTGC': 5,
    's07_ASD_Aspen_Leaf-A_DW92-2_BECKa_AREF': 3,
    's07_ASD_Aspen_Leaf-A_DW92-2_BECKa_AREF': 4,
    's07_ASD_Lawn_Grass_GDS91_green_BECKa_AREF': 6,
    's07_ASD_Lawn_Grass_GDS91_green_BECKa_AREF': 7,
    's07_ASD_Lawn_Grass_GDS91_green_BECKa_AREF': 8,
    's07_ASD_Lawn_Grass_GDS91_green_BECKa_AREF': 9,
    's07_ASD_Lawn_Grass_GDS91_green_BECKa_AREF': 10,
    's07_ASD_Grass_AETR95_CA01-AETR-1_NPV_ASDFRa_AREF': 12,
    's07_ASD_Grass_AETR95_CA01-AETR-1_NPV_ASDFRa_AREF': 14,
    's07_ASD_Concrete_GDS375_Lt_Gry_Road_ASDFRa_AREF': 13,
    's07_ASD_Desert_Varnish_GDS141_BECKa_AREF': 16
}

# 初始化数据结构
data_storage = {stype: {'reflectance': [], 'records': []} for stype in record_mapping}

# 波长参数 (350-2500nm)
original_min_wl = 350
original_max_wl = 2500
target_min_wl = 400
target_max_wl = 900

# 计算波长数组
original_wavelengths = np.arange(original_min_wl, original_max_wl + 1)
target_wavelengths = np.arange(target_min_wl, target_max_wl + 1)

# 创建目标波长掩码
wl_mask = (original_wavelengths >= target_min_wl) & (original_wavelengths <= target_max_wl)

# 处理所有TXT文件
for filename in os.listdir(input_dir):
    if not filename.endswith('.txt'):
        continue

    # 提取基名（不含后缀）
    basename = os.path.splitext(filename)[0]

    # 检查是否在映射中
    if basename not in file_record_map:
        continue

    record_num = file_record_map[basename]
    filepath = os.path.join(input_dir, filename)

    print(f"处理文件: {filename} (记录号: {record_num})")

    try:
        # 读取数据
        with open(filepath, 'r') as f:
            # 跳过标题行
            header = f.readline().strip()

            # 读取光谱数据 (2151个点)
            spectral_data = []
            for _ in range(2151):
                line = f.readline().strip()
                if not line:
                    break
                try:
                    value = float(line)
                    spectral_data.append(value)
                except ValueError:
                    spectral_data.append(np.nan)

        # 转换为数组
        spectral_data = np.array(spectral_data)

        # 验证数据长度
        if len(spectral_data) != 2151:
            print(f"  警告: 数据长度异常 ({len(spectral_data)}行), 期望2151行")
            continue

        # 处理无效值
        spectral_data[spectral_data < -1e30] = np.nan

        # 提取400-900nm范围
        valid_data = spectral_data[wl_mask]

        # 存储数据
        for stype, records in record_mapping.items():
            if record_num in records:
                data_storage[stype]['reflectance'].append(valid_data)
                data_storage[stype]['records'].append(record_num)
                print(f"  添加到 {stype} 类型")
                break

    except Exception as e:
        print(f"  处理文件时出错: {str(e)}")
        continue

# 创建NetCDF文件
for stype, data in data_storage.items():
    if not data['records']:
        print(f"警告: {stype} 无有效数据，跳过生成")
        continue

    nc_filename = os.path.join(output_dir, f"{stype}.nc")

    print(f"创建文件: {nc_filename} ({len(data['records'])}条光谱...")

    try:
        with Dataset(nc_filename, 'w', format='NETCDF4') as nc:
            # 创建维度
            nc.createDimension('wavelength', len(target_wavelengths))
            nc.createDimension('sample', len(data['records']))

            # 添加波长变量
            wl_var = nc.createVariable('wavelength', 'f4', ('wavelength',))
            wl_var[:] = target_wavelengths
            wl_var.units = 'nm'
            wl_var.long_name = 'Wavelength'
            wl_var.actual_range = [target_min_wl, target_max_wl]

            # 添加记录号变量
            rec_var = nc.createVariable('record_number', 'i4', ('sample',))
            rec_var[:] = np.array(data['records'])
            rec_var.long_name = 'USGS Record Number'

            # 添加反射率数据
            refl_data = np.array(data['reflectance'])
            refl_var = nc.createVariable('reflectance', 'f4', ('sample', 'wavelength'),
                                         fill_value=-9999.0, zlib=True)
            refl_var[:, :] = refl_data
            refl_var.units = 'Reflectance'
            refl_var.missing_value = -9999.0
            refl_var.actual_range = [np.nanmin(refl_data), np.nanmax(refl_data)]

            # 添加全局属性
            nc.title = f"USGS高光谱数据 - {stype}类型"
            nc.source = "USGS splib07a数据集"
            nc.history = f"由Python脚本生成于{np.datetime64('now')}"
            nc.original_wavelength_range = f"{original_min_wl}-{original_max_wl}nm"
            nc.target_wavelength_range = f"{target_min_wl}-{target_max_wl}nm"
            nc.author = "自动处理脚本"

        print(f"  成功创建: {nc_filename}")

    except Exception as e:
        print(f"  创建NetCDF文件时出错: {str(e)}")

print("处理完成!")