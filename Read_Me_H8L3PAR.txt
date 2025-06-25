H8L3PAR 数据文件说明
====================

1. 文件命名规则
   - 单时次文件: H8L3PAR_YYYYMMDD_HH00.nc
     示例: H8L3PAR_20150707_0900.nc
   - 月整合文件: H8L3PAR_monthly_YYYYMM.nc
     示例: H8L3PAR_monthly_201507.nc
   - 说明:
     * YYYY: 年份 (4位数字)
     * MM: 月份 (2位数字)
     * DD: 日期 (2位数字)
     * HH: 小时 (UTC时间，2位数字)
     * 00: 分钟固定为00（1小时分辨率）

2. 文件格式
   - 格式类型: NetCDF-4
   - 维度:
        Station: 站点维度 (2014个站点)
        time: 时间维度 (仅月整合文件)
   - 变量: 2个 (单时次文件) 或 3个 (月整合文件)
   - 文件大小:
        单时次文件: 约50-100 KB
        月整合文件: 约5-10 MB (取决于当月天数)

3. 数据内容
   | 变量名   | 描述                         | 单位        | 数据类型 | 维度         | 属性                  |
   |----------|------------------------------|-------------|----------|--------------|-----------------------|
   | Station  | 站点名称                     | 无          | 字符串   | Station      |                       |
   | PAR      | 光合有效辐射                 | umol/m²/s   | float32  | Station      | long_name, units     |
   | SWR      | 短波辐射                     | W/m²        | float32  | Station      | long_name, units     |
   | time     | 时间戳 (仅月整合文件)        | 秒 (UTC)    | float64  | time         | units, calendar       |

4. 数据处理说明
   - 数据转换:
        PAR实际值 = 原始值 × scale_factor + add_offset
        scale_factor = 0.10000000149011612
        add_offset = 0.0
   - 数据质量:
        * 有效值范围: 0-25000 (原始值), 0-2500 (实际值)
        * 缺失值: NaN (原始值为-32768)
   - 时间表示:
        * 单时次文件: 全局属性 time = "HH:00" (UTC时间)
        * 月整合文件: time变量 (秒数, UTC时间)

5. 数据来源
   - 卫星: 日本气象厅向日葵8号/9号(Himawari-8/9)
   - 产品: L3级光合有效辐射(PAR)产品（每小时合成）
   - 分辨率: 0.05度 (约5公里)
   - 原始文件:
        /pub/himawari/L3/PAR/021/YYYYMM/DD/
        H08_YYYYMMDD_HH00_1H_RFL021_FLDK.02401_02401.nc (2022年12月13日前)
        H09_YYYYMMDD_HH00_1H_RFL021_FLDK.02401_02401.nc (2022年12月13日后)
   - 获取方式: 日本宇宙航空研究开发机构(JAXA) P-Tree FTP服务器

6. 使用注意事项
   - 数据包含2014个特定站点的PAR和SWR值
   - 单时次文件每小时生成一个 (UTC时间)
   - 2022年12月13日0000之后的数据来自Himawari-9卫星
   - 月度数据整合后存储在H8L3PAR_monthly_YYYYMM.nc中
   - 处理脚本自动记录缺失文件在H8L3PAR_vacant.csv中

----------------------------------------------------------------

H8L3PAR Data File Documentation
================================

1. File Naming Convention
   - Single-time file: H8L3PAR_YYYYMMDD_HH00.nc
     Example: H8L3PAR_20150707_0900.nc
   - Monthly integrated file: H8L3PAR_monthly_YYYYMM.nc
     Example: H8L3PAR_monthly_201507.nc
   - Description:
     * YYYY: Year (4-digit)
     * MM: Month (2-digit)
     * DD: Day (2-digit)
     * HH: Hour (UTC, 2-digit)
     * 00: Minutes fixed to 00 (1-hour cadence)

2. File Format
   - Format Type: NetCDF-4
   - Dimensions:
        Station: Station dimension (2014 stations)
        time: Time dimension (monthly files only)
   - Variables: 2 (single-time) or 3 (monthly)
   - File Size:
        Single-time: ~50-100 KB
        Monthly: ~5-10 MB (depends on days in month)

3. Data Content
   | Variable  | Description                  | Units       | Data Type | Dimension    | Attributes            |
   |-----------|------------------------------|-------------|-----------|--------------|-----------------------|
   | Station   | Station names                | None        | String    | Station      |                       |
   | PAR       | Photosynthetically active radiation | umol/m²/s | float32   | Station      | long_name, units     |
   | SWR       | Shortwave radiation          | W/m²        | float32   | Station      | long_name, units     |
   | time      | Timestamp (monthly only)     | seconds (UTC)| float64  | time         | units, calendar       |

4. Data Processing Notes
   - Data Conversion:
        PAR_actual = raw_value × scale_factor + add_offset
        scale_factor = 0.10000000149011612
        add_offset = 0.0
   - Data Quality:
        * Valid Range: 0-25000 (raw), 0-2500 (actual)
        * Missing Value: NaN (raw value -32768)
   - Time Representation:
        * Single-time: Global attribute time = "HH:00" (UTC)
        * Monthly: time variable (seconds since 1970-01-01)

5. Data Source
   - Satellite: JMA Himawari-8/9
   - Product: L3 Photosynthetically Active Radiation (PAR) Hourly Composite
   - Resolution: 0.05 degrees (~5 km)
   - Original Files:
        /pub/himawari/L3/PAR/021/YYYYMM/DD/
        H08_YYYYMMDD_HH00_1H_RFL021_FLDK.02401_02401.nc (before 2022-12-13)
        H09_YYYYMMDD_HH00_1H_RFL021_FLDK.02401_02401.nc (after 2022-12-13)
   - Access: JAXA P-Tree FTP Server

6. Usage Notes
   - Contains PAR and SWR values for 2014 specific stations
   - Single-time files generated hourly (UTC time)
   - Data after 2022-12-13 00:00 UTC from Himawari-9 satellite
   - Monthly data integrated in H8L3PAR_monthly_YYYYMM.nc
   - Missing files automatically recorded in H8L3PAR_vacant.csv