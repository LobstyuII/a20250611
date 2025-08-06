import os
import xarray as xr
import numpy as np
import shutil
import logging
from tqdm import tqdm
import datetime
import re

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 定义路径
base_path = r"D:/H8_data"
coefficients_path = os.path.join(base_path, "USGS", "BRDF_conversion_coefficients.nc")
modis_brdf_dir = os.path.join(base_path, "MODIS_BRDF_Albedo")
himawari_brdf_dir = os.path.join(base_path, "Himawari_BRDF_Albedo")
lc_path = os.path.join(base_path, "LC_resampled_2015_2024.nc")

# 土地覆盖类型映射 (MODIS IGBP分类到自定义类别)
landcover_types = {
    'Evergreen': [1, 2, 5],
    'Deciduous': [3, 4],
    'Grass': [6, 7, 8, 9, 10],
    'Cropland': [12, 14],
    'Urban': [13],
    'Barren': [16]
}

# 无效像素类型 (雪/冰和水体)
INVALID_LC_TYPES = [15, 17]

# 创建IGBP代码到自定义类别的映射
igbp_to_lctype = {}
for lc_type, codes in landcover_types.items():
    for code in codes:
        igbp_to_lctype[code] = lc_type


# 加载转换系数
def load_conversion_coefficients():
    """加载BRDF转换系数"""
    try:
        ds = xr.open_dataset(coefficients_path)
        coefficients = {
            'Red': {},
            'NIR': {}
        }

        for lc_type in ds.landcover.values:
            coefficients['Red'][lc_type] = ds.red_coef.sel(landcover=lc_type).item()
            coefficients['NIR'][lc_type] = ds.nir_coef.sel(landcover=lc_type).item()

        logger.info("成功加载BRDF转换系数")
        return coefficients
    except Exception as e:
        logger.error(f"加载转换系数失败: {e}")
        raise


# 加载年度土地覆盖数据 (修复时间单位问题)
def load_annual_landcover():
    """加载年度土地覆盖数据"""
    try:
        # 使用decode_times=False避免时间解码问题
        lc_ds = xr.open_dataset(lc_path, decode_times=False)

        # 提取站点信息
        stations = lc_ds['Station'].values
        lats = lc_ds['Lat'].values
        lons = lc_ds['Lon'].values

        # 手动处理时间变量
        time_values = lc_ds['time'].values
        # 将时间转换为年份 (2015-2024)
        years = [2015 + int(t) for t in time_values]

        # 创建年份到时间索引的映射
        year_index_map = {year: idx for idx, year in enumerate(years)}

        logger.info(f"成功加载土地覆盖数据: {len(stations)}个站点, {len(years)}个年份 (2015-2024)")
        return lc_ds, stations, lats, lons, year_index_map
    except Exception as e:
        logger.error(f"加载土地覆盖数据失败: {e}")
        raise


# 获取特定年份的土地覆盖类型
def get_lc_types_for_year(lc_ds, year_index_map, year):
    """
    获取特定年份的土地覆盖类型

    参数:
        lc_ds: 土地覆盖数据集
        year_index_map: 年份到时间索引的映射
        year: 目标年份

    返回:
        lc_types: 该年份各站点的土地覆盖类型列表
        lc_codes: 该年份各站点的原始IGBP代码列表
    """
    if year not in year_index_map:
        logger.error(f"年份 {year} 不在土地覆盖数据范围内 (2015-2024)")
        return None, None

    time_idx = year_index_map[year]
    lc_codes = lc_ds['LC_type1'].isel(time=time_idx).values

    # 将IGBP代码转换为自定义类别
    lc_types = []
    for code in lc_codes:
        # 检查是否为无效类型 (雪/冰或水体)
        if int(code) in INVALID_LC_TYPES:
            lc_types.append('Invalid')
        else:
            # 如果代码在映射中，使用对应类别；否则使用'Barren'作为默认值
            lc_types.append(igbp_to_lctype.get(int(code), 'Barren'))

    return lc_types, lc_codes


# 从文件名提取年份
def extract_year_from_filename(filename):
    """从文件名中提取年份"""
    match = re.search(r'MODIS_BRDF_Albedo_(\d{4})\d{4}\.nc', filename)
    if match:
        return int(match.group(1))
    else:
        logger.warning(f"无法从文件名提取年份: {filename}")
        return None


# 转换单个BRDF文件
def convert_brdf_file(input_path, output_path, coefficients, lc_ds, year_index_map):
    """
    转换单个MODIS BRDF文件到Himawari格式

    算法逻辑:
    1. 对于每个站点的红光波段(Band1)参数:
        - 如果土地覆盖类型为无效(15或17): 设置为-9999
        - 否则: Himawari_参数 = MODIS_参数 × Red_系数[土地覆盖类型]

    2. 对于每个站点的近红外波段(Band2)参数:
        - 如果土地覆盖类型为无效(15或17): 设置为-9999
        - 否则: Himawari_参数 = MODIS_参数 × NIR_系数[土地覆盖类型]

    3. 转换公式适用于所有三个BRDF参数(f_iso, f_vol, f_geo)
    """
    try:
        # 从文件名提取年份
        filename = os.path.basename(input_path)
        year = extract_year_from_filename(filename)
        if year is None:
            logger.error(f"无法确定年份: {input_path}")
            return False

        # 获取该年份的土地覆盖类型
        lc_types, lc_codes = get_lc_types_for_year(lc_ds, year_index_map, year)
        if lc_types is None:
            return False

        # 读取输入文件
        ds = xr.open_dataset(input_path)

        # 创建输出数据集
        output_data = {}

        # 复制所有非BRDF变量
        for var in ds.variables:
            if var not in ['Band1_iso', 'Band1_vol', 'Band1_geo',
                           'Band2_iso', 'Band2_vol', 'Band2_geo']:
                output_data[var] = ds[var]

        # 添加土地覆盖类型作为新变量
        output_data['LC_type1'] = xr.DataArray(
            lc_codes,
            dims=('Station',),
            attrs={
                'long_name': 'IGBP Land Cover Type',
                'units': 'class',
                'comment': '15: Snow/Ice, 17: Water - treated as invalid pixels'
            }
        )

        # 转换红光波段参数
        for param in ['iso', 'vol', 'geo']:
            var_name = f'Band1_{param}'
            modis_values = ds[var_name].values

            # 应用转换系数
            himawari_values = np.full_like(modis_values, -9999.0)
            for i, value in enumerate(modis_values):
                lc_type = lc_types[i]

                # 处理无效像素
                if lc_type == 'Invalid':
                    continue  # 保持为-9999
                else:
                    # 检查原始值是否有效
                    if not np.isclose(value, -9999.0):
                        a_red = coefficients['Red'].get(lc_type, 1.0)  # 默认系数为1.0
                        himawari_values[i] = value * a_red

            output_data[var_name] = xr.DataArray(
                himawari_values,
                dims=ds[var_name].dims,
                attrs={
                    'long_name': f'Himawari red band BRDF {param} parameter',
                    'units': 'unitless',
                    'conversion_coefficient': a_red if lc_type != 'Invalid' else -9999,
                    'source_landcover': lc_type,
                    'source': f'Converted from MODIS using {lc_type} coefficient' if lc_type != 'Invalid' else 'Invalid pixel (snow/ice or water)'
                }
            )

        # 转换近红外波段参数
        for param in ['iso', 'vol', 'geo']:
            var_name = f'Band2_{param}'
            modis_values = ds[var_name].values

            # 应用转换系数
            himawari_values = np.full_like(modis_values, -9999.0)
            for i, value in enumerate(modis_values):
                lc_type = lc_types[i]

                # 处理无效像素
                if lc_type == 'Invalid':
                    continue  # 保持为-9999
                else:
                    # 检查原始值是否有效
                    if not np.isclose(value, -9999.0):
                        a_nir = coefficients['NIR'].get(lc_type, 1.0)  # 默认系数为1.0
                        himawari_values[i] = value * a_nir

            output_data[var_name] = xr.DataArray(
                himawari_values,
                dims=ds[var_name].dims,
                attrs={
                    'long_name': f'Himawari NIR band BRDF {param} parameter',
                    'units': 'unitless',
                    'conversion_coefficient': a_nir if lc_type != 'Invalid' else -9999,
                    'source_landcover': lc_type,
                    'source': f'Converted from MODIS using {lc_type} coefficient' if lc_type != 'Invalid' else 'Invalid pixel (snow/ice or water)'
                }
            )

        # 添加全局属性说明转换过程
        attrs = ds.attrs.copy()
        attrs['title'] = 'Himawari Adjusted BRDF Albedo Parameters'
        attrs['conversion_method'] = 'Scaled MODIS BRDF parameters using landcover-specific coefficients'
        attrs['invalid_pixels'] = 'Land cover types 15 (Snow/Ice) and 17 (Water) are treated as invalid'
        attrs['conversion_coefficients_source'] = coefficients_path
        attrs['conversion_landcover_source'] = lc_path
        attrs['conversion_year'] = str(year)
        attrs['conversion_date'] = str(datetime.datetime.now())

        # 创建输出数据集
        output_ds = xr.Dataset(output_data, attrs=attrs)

        # 保存输出文件
        output_ds.to_netcdf(output_path)
        logger.info(f"成功转换: {filename} (年份: {year})")
        return True

    except Exception as e:
        logger.error(f"转换文件 {input_path} 失败: {e}")
        return False


# 主处理函数
def main():
    # 确保输出目录存在
    os.makedirs(himawari_brdf_dir, exist_ok=True)

    # 加载必要数据
    coefficients = load_conversion_coefficients()
    lc_ds, stations, lats, lons, year_index_map = load_annual_landcover()

    # 获取所有需要处理的MODIS BRDF文件
    modis_files = []
    for root, dirs, files in os.walk(modis_brdf_dir):
        for file in files:
            if file.endswith('.nc') and file.startswith('MODIS_BRDF_Albedo'):
                modis_files.append(os.path.join(root, file))

    logger.info(f"找到 {len(modis_files)} 个MODIS BRDF文件需要转换")

    # 处理每个文件
    success_count = 0
    for input_path in tqdm(modis_files, desc="转换BRDF文件"):
        # 构建输出路径 (保持相同的目录结构)
        rel_path = os.path.relpath(input_path, modis_brdf_dir)

        # 修改输出文件名：将"MODIS_BRDF_Albedo"替换为"Himawari_adjusted_Albedo"
        new_filename = os.path.basename(rel_path).replace("MODIS_BRDF_Albedo", "Himawari_adjusted_BRDF_Albedo")
        output_path = os.path.join(himawari_brdf_dir, os.path.dirname(rel_path), new_filename)

        # 确保输出目录存在
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 转换文件
        if convert_brdf_file(input_path, output_path, coefficients, lc_ds, year_index_map):
            success_count += 1

    logger.info(f"转换完成! 成功: {success_count}/{len(modis_files)}")


if __name__ == "__main__":
    main()