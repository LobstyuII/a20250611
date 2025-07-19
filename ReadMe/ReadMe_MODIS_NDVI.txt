# MODIS NDVI 数据文件说明 (重采样到Himawari 5km网格)
====================

## 1. 文件命名规则
- **单日文件**: `MODIS_NDVI_YYYYMMDD.nc`
  示例: `MODIS_NDVI_20150707.nc`
- **整合文件**: `MODIS_NDVI_combined.nc`
  (包含所有站点的完整时间序列数据)
- **说明**:
  - `YYYY`: 年份 (4位数字)
  - `MM`: 月份 (2位数字)
  - `DD`: 日期 (2位数字)

## 2. 文件格式
- **格式类型**: NetCDF-4
- **维度**:
  - `Station`: 站点维度 (固定数量的站点)
  - `time`: 时间维度 (仅整合文件)
- **文件大小**:
  - 单日文件: 约100-200 KB
  - 整合文件: 约100-200 MB (取决于时间范围长度)

## 3. 数据内容
| 变量名       | 描述                         | 单位        | 数据类型 | 维度         | 属性                  |
|--------------|------------------------------|-------------|----------|--------------|-----------------------|
| Station      | 站点名称                     | 无          | 字符串   | Station      |                       |
| Lat          | 站点原始纬度                 | 度          | float32  | Station      | long_name, units     |
| Lon          | 站点原始经度                 | 度          | float32  | Station      | long_name, units     |
| grid_x       | Himawari网格X索引            | 无          | int32    | Station      | long_name            |
| grid_y       | Himawari网格Y索引            | 无          | int32    | Station      | long_name            |
| NDVI_Terra   | Terra卫星的NDVI值 (5km网格均值)| 无          | float32  | Station      | long_name, fill_value|
| NDVI_Aqua    | Aqua卫星的NDVI值 (5km网格均值) | 无          | float32  | Station      | long_name, fill_value|
| time         | 时间戳 (仅整合文件)          | 天 (UTC)    | float64  | time         | units, calendar       |

## 4. 数据处理说明
- **数据质量**:
  - 有效值范围: -1.0 到 1.0
  - 缺失值: -9999.0
- **网格重采样**:
  - 每个站点的NDVI值代表对应Himawari 5km网格内所有MODIS 500m像元的平均值
  - Himawari网格计算:
    ```
    grid_x = floor((lon - 80) / 0.05)
    grid_y = floor((60 - lat) / 0.05)
    ```
  - 网格边界:
    - 西边界: 80 + grid_x * 0.05
    - 东边界: 西边界 + 0.05
    - 北边界: 60 - grid_y * 0.05
    - 南边界: 北边界 - 0.05
- **时间表示**:
  - 单日文件: 全局属性 `date = "YYYY-MM-DD"`
  - 整合文件: time变量 (天数，相对于1970-01-01)
- **数据来源**:
  - Terra卫星: MOD09GA产品
  - Aqua卫星: MYD09GA产品

## 5. 数据来源
- **卫星**: Terra (EOS AM-1) 和 Aqua (EOS PM-1)
- **产品**: MODIS/Terra+Aqua Surface Reflectance Daily L2G Global 1km and 500m SIN Grid V006
- **原始分辨率**: 500米
- **重采样分辨率**: 5km (匹配Himawari网格)
- **波段**: NDVI (归一化植被指数)
- **获取方式**: Google Earth Engine (GEE) 平台
  - Terra集合: `MODIS/MOD09GA_006_NDVI`
  - Aqua集合: `MODIS/MYD09GA_006_NDVI`

## 6. 使用注意事项
1. 数据包含固定站点的每日NDVI观测值，已重采样到Himawari 5km网格
2. `grid_x`和`grid_y`可直接匹配Himawari数据网格坐标
3. 单日文件组织在年/月目录结构中:
   ```
   MODIS_NDVI/
   ├── YYYY/
   │   └── MM/
   │       └── MODIS_NDVI_YYYYMMDD.nc
   ```
4. 整合文件包含所有日期的完整时间序列
5. 处理脚本自动跳过已存在且完整的文件
6. 由于GEE配额限制，并行下载线程数设置为5

---

# MODIS NDVI Data File Documentation (Resampled to Himawari 5km Grid)
================================

## 1. File Naming Convention
- **Daily file**: `MODIS_NDVI_YYYYMMDD.nc`
  Example: `MODIS_NDVI_20150707.nc`
- **Combined file**: `MODIS_NDVI_combined.nc`
  (Complete time series for all stations)
- **Description**:
  - `YYYY`: Year (4-digit)
  - `MM`: Month (2-digit)
  - `DD`: Day (2-digit)

## 2. File Format
- **Format Type**: NetCDF-4
- **Dimensions**:
  - `Station`: Station dimension (fixed number of stations)
  - `time`: Time dimension (combined file only)
- **File Size**:
  - Daily file: ~100-200 KB
  - Combined file: ~100-200 MB (depends on time period)

## 3. Data Content
| Variable     | Description                  | Units       | Data Type | Dimension    | Attributes            |
|--------------|------------------------------|-------------|-----------|--------------|-----------------------|
| Station      | Station names                | None        | String    | Station      |                       |
| Lat          | Original station latitude    | degrees     | float32   | Station      | long_name, units     |
| Lon          | Original station longitude   | degrees     | float32   | Station      | long_name, units     |
| grid_x       | Himawari grid X index        | None        | int32     | Station      | long_name            |
| grid_y       | Himawari grid Y index        | None        | int32     | Station      | long_name            |
| NDVI_Terra   | NDVI from Terra (5km mean)   | None        | float32   | Station      | long_name, fill_value|
| NDVI_Aqua    | NDVI from Aqua (5km mean)    | None        | float32   | Station      | long_name, fill_value|
| time         | Timestamp (combined only)    | days (UTC)  | float64   | time         | units, calendar       |

## 4. Data Processing Notes
- **Data Quality**:
  - Valid Range: -1.0 to 1.0
  - Missing Value: -9999.0
- **Grid Resampling**:
  - NDVI values represent mean of all MODIS 500m pixels within corresponding Himawari 5km grid
  - Himawari grid calculation:
    ```
    grid_x = floor((lon - 80) / 0.05)
    grid_y = floor((60 - lat) / 0.05)
    ```
  - Grid boundaries:
    - West: 80 + grid_x * 0.05
    - East: West + 0.05
    - North: 60 - grid_y * 0.05
    - South: North - 0.05
- **Time Representation**:
  - Daily file: Global attribute `date = "YYYY-MM-DD"`
  - Combined file: time variable (days since 1970-01-01)
- **Data Sources**:
  - Terra satellite: MOD09GA product
  - Aqua satellite: MYD09GA product

## 5. Data Source
- **Satellites**: Terra (EOS AM-1) and Aqua (EOS PM-1)
- **Product**: MODIS/Terra+Aqua Surface Reflectance Daily L2G Global 1km and 500m SIN Grid V006
- **Original Resolution**: 500m
- **Resampled Resolution**: 5km (matched to Himawari grid)
- **Band**: NDVI (Normalized Difference Vegetation Index)
- **Access**: Google Earth Engine (GEE) Platform
  - Terra collection: `MODIS/MOD09GA_006_NDVI`
  - Aqua collection: `MODIS/MYD09GA_006_NDVI`

## 6. Usage Notes
1. Contains daily NDVI observations resampled to Himawari 5km grid
2. `grid_x` and `grid_y` directly match Himawari data grid coordinates
3. Daily files organized in year/month directory structure:
   ```
   MODIS_NDVI/
   ├── YYYY/
   │   └── MM/
   │       └── MODIS_NDVI_YYYYMMDD.nc
   ```
4. Combined file contains complete time series
5. Processing script skips existing complete files
6. Parallel download threads set to 5 due to GEE quota limits

