### ERA5 数据文件说明
=============================

1. **文件命名规则**
   - 单时次文件: `ERA5_YYYYMMDD_HH00.nc`
     示例: `ERA5_20150707_0900.nc`
   - 说明:
     * `YYYY`: 年份 (4位数字)
     * `MM`: 月份 (2位数字)
     * `DD`: 日期 (2位数字)
     * `HH`: 小时 (UTC时间，2位数字)
     * `00`: 分钟固定为00（1小时分辨率）

2. **文件格式**
   - 格式类型: NetCDF-4
   - 维度:
        `Station`: 站点维度 (2014个站点)
   - 变量: 9个
   - 文件大小:
        单时次文件: 约80-120 KB

3. **数据内容**
| 变量名                     | 描述                          | 单位    | 数据类型 | 维度         | 属性                  |
|----------------------------|-------------------------------|---------|----------|--------------|-----------------------|
| Station                    | 站点名称                      | 无      | 字符串   | Station      |                       |
| Lat                        | 纬度                          | °N      | float32  | Station      | long_name, units      |
| Lon                        | 经度                          | °E      | float32  | Station      | long_name, units      |
| dewpoint_temperature_2m    | 2米露点温度                   | K       | float32  | Station      | long_name, units      |
| temperature_2m             | 2米气温                       | K       | float32  | Station      | long_name, units      |
| surface_pressure           | 地表气压                      | Pa      | float32  | Station      | long_name, units      |
| total_precipitation        | 总降水量                      | m       | float32  | Station      | long_name, units      |
| u_component_of_wind_10m    | 10米风场U分量（东向）         | m/s     | float32  | Station      | long_name, units      |
| v_component_of_wind_10m    | 10米风场V分量（北向）         | m/s     | float32  | Station      | long_name, units      |

4. **数据处理说明**
   - 维度转换:
        * 移除原始时间维度
        * 所有变量转换为1维结构 (2014个站点)
   - 数据质量:
        * 缺失值: `-9999.0`
        * 有效值范围: 根据变量物理特性确定
   - 时间表示:
        * 全局属性 `time = "YYYY-MM-DD HH:00:00"` (UTC时间)

5. **数据来源**
   - 再分析数据: ECMWF ERA5-Land 每小时数据
   - 分辨率: 0.1°×0.1° (约9公里)
   - 原始数据获取方式: Google Earth Engine 平台
   - 处理平台: Python 使用 `ee` 和 `xarray` 库

6. **使用注意事项**
   - 包含2014个特定站点的气象要素
   - 单时次文件每小时一个 (UTC时间)
   - 数据目录结构保持原始层级: `/年/月/文件.nc`
   - 数据时间范围: 2015年1月1日至今（根据实际请求）

---

### ERA5 Data File Documentation
============================================

1. **File Naming Convention**
   - Single-time file: `ERA5_YYYYMMDD_HH00.nc`
     Example: `ERA5_20150707_0900.nc`
   - Description:
     * `YYYY`: Year (4-digit)
     * `MM`: Month (2-digit)
     * `DD`: Day (2-digit)
     * `HH`: Hour (UTC, 2-digit)
     * `00`: Minutes fixed to 00 (1-hour cadence)

2. **File Format**
   - Format Type: NetCDF-4
   - Dimensions:
        `Station`: Station dimension (2014 stations)
   - Variables: 9
   - File Size:
        Single-time: ~80-120 KB

3. **Data Content**
| Variable                     | Description                   | Units   | Data Type | Dimension    | Attributes            |
|------------------------------|-------------------------------|---------|-----------|--------------|-----------------------|
| Station                      | Station names                 | None    | String    | Station      |                       |
| Lat                          | Latitude                      | °N      | float32   | Station      | long_name, units      |
| Lon                          | Longitude                     | °E      | float32   | Station      | long_name, units      |
| dewpoint_temperature_2m      | 2m dewpoint temperature       | K       | float32   | Station      | long_name, units      |
| temperature_2m               | 2m air temperature            | K       | float32   | Station      | long_name, units      |
| surface_pressure             | Surface pressure              | Pa      | float32   | Station      | long_name, units      |
| total_precipitation          | Total precipitation           | m       | float32   | Station      | long_name, units      |
| u_component_of_wind_10m      | 10m U wind component (eastward) | m/s   | float32   | Station      | long_name, units      |
| v_component_of_wind_10m      | 10m V wind component (northward)| m/s   | float32   | Station      | long_name, units      |

4. **Data Processing Notes**
   - Dimension Conversion:
        * Original time dimension removed
        * All variables flattened to 1D (2014 stations)
   - Data Quality:
        * Missing value: `-9999.0`
        * Valid range: Variable-dependent physical limits
   - Time Representation:
        * Global attribute `time = "YYYY-MM-DD HH:00:00"` (UTC)

5. **Data Source**
   - Reanalysis: ECMWF ERA5-Land hourly data
   - Resolution: 0.1°×0.1° (~9 km)
   - Original Access: Google Earth Engine API
   - Processing Platform: Python with `ee` and `xarray` libraries

6. **Usage Notes**
   - Contains meteorological parameters for 2014 specific stations
   - Single-time files generated hourly (UTC time)
   - Maintains original directory structure: `/year/month/file.nc`
   - Temporal coverage: January 1, 2015 to present (request-dependent)