# H8NDVI 数据文件说明
====================

## 1. 文件命名规则
   - 单时次文件: `NDVI_YYYYMMDD_HH00.nc`
     示例: `NDVI_20150707_0000.nc`
   - 说明:
     * `YYYY`: 年份 (4位数字)
     * `MM`: 月份 (2位数字)
     * `DD`: 日期 (2位数字)
     * `HH00`: UTC时间（小时，2位数字），分钟固定为00

## 2. 文件格式
   - **格式类型**: NetCDF-4
   - **维度**:
     * `station`: 站点维度（数量由LUTs.nc决定）
   - **变量**: 4个
   - **文件大小**: 约50-150 KB（取决于站点数量）
   - **时间范围**: 每日0-12时和21-23时（UTC）

## 3. 数据内容
| 变量名                | 描述                     | 单位    | 数据类型 | 维度      | 属性                                                                 |
|-----------------------|--------------------------|---------|----------|-----------|----------------------------------------------------------------------|
| Station               | 站点名称                 | 无      | 字符串   | station   |                                                                      |
| General_availability  | 通用可用性标志           | 无      | int8     | station   |                                                                      |
| valid_flag            | 有效像素标志             | 无      | int8     | station   |                                                                      |
| **NDVI**              | 归一化植被指数           | 无      | float32  | station   | `units="unitless"`, `long_name="Normalized Difference Vegetation Index"`, `valid_range=[-1.0, 1.0]`, `description="Calculated from surface reflectance bands 3 and 4"` |

## 4. 数据处理说明
   - **NDVI计算公式**:
     `NDVI = (Albedo_04 - Albedo_03) / (Albedo_04 + Albedo_03)`
     * 红波段: `Albedo_03` (0.64μm)
     * 近红外波段: `Albedo_04` (0.86μm)

   - **数据质量控制**:
     * 仅处理有效像素：分母>0 且波段值非负
     * 结果强制限制在[-1, 1]范围内
     * 无效值设为NaN

   - **处理统计**:
     * 输出日志包含有效像素比例（示例：`Valid NDVI pixels: 1500/2014 (74.48%)`）

## 5. 数据来源
   - **卫星**: 日本气象厅向日葵8号 (Himawari-8)
   - **输入产品**: L2级地表反射率 (SR)
   - **分辨率**: 站点级数据（非网格）
   - **原始数据路径**:
     `D:/H8_Data/H8SR/SR_YYYYMMDD_HH00.nc`
   - **站点坐标文件**:
     `D:/H8_data/LUTs.nc` (包含经纬度信息)
   - **时间范围**: 2015年7月7日 - 2016年1月1日

## 6. 使用注意事项
   - 输出路径: `D:/H8_Data/H8NDVI/`
   - 仅当输入SR文件存在时生成NDVI文件
   - 已存在输出文件时自动跳过处理
   - 使用多进程并行处理（最大进程数=CPU核心数/2）
   - 全局属性包含关键元数据：
     ```python
     title = 'Himawari-8 NDVI Product'
     time = "HH00"  # UTC时间
     date = "YYYYMMDD"
     reference = "NDVI = (NIR - Red) / (NIR + Red)"
     ```
   - 错误文件会记录详细失败原因

---

# H8NDVI Data File Documentation
================================

## 1. File Naming Convention
   - Single-time file: `NDVI_YYYYMMDD_HH00.nc`
     Example: `NDVI_20150707_0000.nc`
   - Format:
     * `YYYY`: Year (4-digit)
     * `MM`: Month (2-digit)
     * `DD`: Day (2-digit)
     * `HH00`: UTC hour (2-digit), minutes fixed to 00

## 2. File Format
   - **Format Type**: NetCDF-4
   - **Dimensions**:
     * `station`: Station dimension (size from LUTs.nc)
   - **Variables**: 4
   - **File Size**: ~50-150 KB (station-dependent)
   - **Time Coverage**: Daily 00:00-12:00 & 21:00-23:00 UTC

## 3. Data Content
| Variable               | Description              | Units  | Data Type | Dimension | Attributes                                                                 |
|------------------------|--------------------------|--------|-----------|-----------|----------------------------------------------------------------------------|
| Station                | Station names            | None   | String    | station   |                                                                            |
| General_availability   | General availability flag| None   | int8      | station   |                                                                            |
| valid_flag             | Valid pixel flag         | None   | int8      | station   |                                                                            |
| **NDVI**               | Normalized Difference Vegetation Index | None | float32   | station   | `units="unitless"`, `long_name="Normalized Difference Vegetation Index"`, `valid_range=[-1.0, 1.0]`, `description="Calculated from surface reflectance bands 3 and 4"` |

## 4. Data Processing
   - **NDVI Formula**:
     `NDVI = (Albedo_04 - Albedo_03) / (Albedo_04 + Albedo_03)`
     * Red band: `Albedo_03` (0.64μm)
     * NIR band: `Albedo_04` (0.86μm)

   - **Quality Control**:
     * Processes only valid pixels: denominator>0 & non-negative band values
     * Results clamped to [-1, 1] range
     * Invalid values set to NaN

   - **Processing Statistics**:
     * Logs include valid pixel ratio (e.g., `Valid NDVI pixels: 1500/2014 (74.48%)`)

## 5. Data Source
   - **Satellite**: JMA Himawari-8
   - **Input Product**: Level 2 Surface Reflectance (SR)
   - **Resolution**: Station-level (non-gridded)
   - **Source Data Path**:
     `D:/H8_Data/H8SR/SR_YYYYMMDD_HH00.nc`
   - **Station Coordinate File**:
     `D:/H8_data/LUTs.nc` (contains lat/lon)
   - **Time Period**: 2015-07-07 to 2016-01-01

## 6. Usage Notes
   - **Output Path**: `D:/H8_Data/H8NDVI/`
   - Files generated only when input SR exists
   - Skips processing if output exists
   - Uses multiprocessing (max_workers = CPU_cores/2)
   - Global attributes include critical metadata:
     ```python
     title = 'Himawari-8 NDVI Product'
     time = "HH00"  # UTC hour
     date = "YYYYMMDD"
     reference = "NDVI = (NIR - Red) / (NIR + Red)"
     ```
   - Detailed error logging for failed files