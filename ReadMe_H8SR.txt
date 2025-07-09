### H8SR 数据文件说明  
**(Himawari-8 地表反射率产品)**  

---

#### 1. 文件命名规则  
- **单时次文件**: `SR_YYYYMMDD_HH00.nc`  
  示例: `SR_20150707_0900.nc`  
- **说明**:  
  - `YYYY`: 年份 (4位数字)  
  - `MM`: 月份 (2位数字)  
  - `DD`: 日期 (2位数字)  
  - `HH`: UTC小时 (2位数字)  
  - `00`: 分钟固定为00  

---

#### 2. 文件格式  
- **格式类型**: NetCDF-4  
- **维度**:  
  - `station`: 站点维度 (2014个站点)  
- **文件大小**: 约 200-500 KB  

---

#### 3. 数据内容  
| 变量名                 | 描述                     | 单位/类型     | 维度       | 属性                     |  
|------------------------|--------------------------|---------------|------------|--------------------------|  
| `Station`              | 站点名称                 | 字符串        | `station`  |                          |  
| `General_availability` | 综合数据可用性标志       | `int8`        | `station`  | `0=不可用, 1=可用`       |  
| `valid_flag`           | 地表反射率计算有效性标志 | `int8`        | `station`  | `0=无效, 1=有效`         |  
| `Albedo_01`            | 0.47μm 波段地表反射率    | `float32`     | `station`  | `units="reflectance"`    |  
| `Albedo_02`            | 0.51μm 波段地表反射率    | `float32`     | `station`  | `units="reflectance"`    |  
| `Albedo_03`            | 0.64μm 波段地表反射率    | `float32`     | `station`  | `units="reflectance"`    |  
| `Albedo_04`            | 0.86μm 波段地表反射率    | `float32`     | `station`  | `units="reflectance"`    |  

> **全局属性**:  
> - `title`: "Himawari-8 Surface Reflectance Product"  
> - `source`: "6S atmospheric correction with BRDF normalization"  
> - `date`: 数据日期 (YYYYMMDD)  
> - `time`: UTC时间 (HH00)  

---

#### 4. 数据处理说明  
1. **输入数据**:  
   - TOA反射率及角度 (`Hourly_TOA_Angles`)  
   - MERRA2 大气参数 (臭氧 `TO3`/水汽 `TQV`)  
   - H8L3ARP 气溶胶光学厚度 (`AOT`)  
   - 土地利用分类 (`LC_2015_2024.nc`)  

2. **关键处理**:  
   - **单位转换**:  
     - 臭氧: Dobson → cm-atm (`TO3×0.001`)  
     - 水汽: kg/m² → g/cm² (`TQV×0.1`)  
     - AOT 500nm → 550nm (`τ₅₅₀ = τ₅₀₀×(500/550)¹·³`)  
   - **BRDF模型选择** (基于17类LUCC):  
     | LUCC类型 | 模型        | 典型地表       |  
     |----------|-------------|----------------|  
     | 1-7      | Rahman      | 植被/土壤      |  
     | 8,9,13   | Walthall    | 城市/冰雪      |  
     | 其他     | Lambertian  | 水体/沙漠      |  
   - **时空范围**:  
     - 日期: 2015-07-07 至 2016-12-31  
     - UTC时间: 0-12时 + 21-23时  

3. **质量控制**:  
   - 缺失值: `NaN`  
   - 有效性标志: `valid_flag=1` 表示成功计算  

---

#### 5. 数据来源  
| 数据类型       | 来源                          | 分辨率       | 原始路径                     |  
|----------------|-------------------------------|--------------|------------------------------|  
| TOA反射率      | Himawari-8/9 卫星             | 0.05度       | `D:/H8_data/Hourly_TOA_Angles/` |  
| 大气参数       | MERRA2 再分析资料             | 0.5°×0.625°  | `D:/H8_data/MERRA2/`            |  
| AOD            | H8L3ARP 产品                 | 0.05度       | `D:/H8_data/H8L3ARP/`           |  
| 土地利用       | LC_2015_2024.nc              | 站点尺度     | `D:/H8_data/LC_2015_2024.nc`    |  

---

#### 6. 使用注意事项  
1. **站点覆盖**: 固定2014个站点  
2. **卫星切换**:  
   - ≤2022-12-12: Himawari-8  
   - ≥2022-12-13: Himawari-9  
3. **数据有效性**:  
   - `General_availability=0`: 输入数据缺失  
   - `valid_flag=0`: 算法失败 (反射率=`NaN`)  
4. **文件生成**:  
   - 跳过已存在文件  
   - 缺失输入时自动跳过  
5. **并行处理**: 默认进程数 = CPU核心数/2  

> **处理日志示例**:
> `[2025-07-01 14:30:00] [SUCCESS] Generated SR_20150707_0900.nc - Valid stations: 1800/2014 (89.37%)`

---
----------------------------------------------------------------  

### H8SR Data File Documentation  
**(Himawari-8 Surface Reflectance Product)**  

---

#### 1. File Naming Convention  
- **Single-time file**: `SR_YYYYMMDD_HH00.nc`  
  Example: `SR_20150707_0900.nc`  
- **Description**:  
  - `YYYY`: Year (4-digit)  
  - `MM`: Month (2-digit)  
  - `DD`: Day (2-digit)  
  - `HH`: Hour (UTC, 2-digit)  
  - `00`: Minutes fixed to 00  

---

#### 2. File Format  
- **Format Type**: NetCDF-4  
- **Dimensions**:  
  - `station`: Station dimension (2014 stations)  
- **File Size**: ~200-500 KB  

---

#### 3. Data Content  
| Variable               | Description                  | Units/Type    | Dimension   | Attributes               |  
|------------------------|------------------------------|---------------|-------------|--------------------------|  
| `Station`              | Station names                | String        | `station`   |                          |  
| `General_availability` | Data availability flag       | `int8`        | `station`   | `0=unavailable, 1=available` |  
| `valid_flag`           | SR calculation validity flag | `int8`        | `station`   | `0=invalid, 1=valid`     |  
| `Albedo_01`            | 0.47μm band surface reflectance | `float32`     | `station`   | `units="reflectance"`    |  
| `Albedo_02`            | 0.51μm band surface reflectance | `float32`     | `station`   | `units="reflectance"`    |  
| `Albedo_03`            | 0.64μm band surface reflectance | `float32`     | `station`   | `units="reflectance"`    |  
| `Albedo_04`            | 0.86μm band surface reflectance | `float32`     | `station`   | `units="reflectance"`    |  

> **Global Attributes**:  
> - `title`: "Himawari-8 Surface Reflectance Product"  
> - `source`: "6S atmospheric correction with BRDF normalization"  
> - `date`: Data date (YYYYMMDD)  
> - `time`: UTC time (HH00)  

---

#### 4. Data Processing Notes  
1. **Input Data**:  
   - TOA reflectance & angles (`Hourly_TOA_Angles`)  
   - MERRA2 atmospheric parameters (`TO3`/`TQV`)  
   - H8L3ARP Aerosol Optical Depth (`AOT`)  
   - Land Use Classification (`LC_2015_2024.nc`)  

2. **Key Processing**:  
   - **Unit Conversion**:  
     - Ozone: Dobson → cm-atm (`TO3×0.001`)  
     - Water Vapor: kg/m² → g/cm² (`TQV×0.1`)  
     - AOT 500nm → 550nm (`τ₅₅₀ = τ₅₀₀×(500/550)¹·³`)  
   - **BRDF Model Selection** (by 17 LUCC types):  
     | LUCC Type | Model       | Typical Surface |  
     |-----------|-------------|-----------------|  
     | 1-7       | Rahman      | Vegetation/Soil |  
     | 8,9,13    | Walthall    | Urban/Snow      |  
     | Others    | Lambertian  | Water/Desert    |  
   - **Spatiotemporal Coverage**:  
     - Date: 2015-07-07 to 2016-12-31  
     - UTC Hours: 0-12 + 21-23  

3. **Quality Control**:  
   - Missing Value: `NaN`  
   - Validity Flag: `valid_flag=1` indicates successful calculation  

---

#### 5. Data Source  
| Data Type       | Source                          | Resolution    | Original Path               |  
|-----------------|---------------------------------|---------------|-----------------------------|  
| TOA Reflectance | Himawari-8/9 Satellite          | 0.05-degree   | `D:/H8_data/Hourly_TOA_Angles/` |  
| Atmospheric     | MERRA2 Reanalysis               | 0.5°×0.625°   | `D:/H8_data/MERRA2/`            |  
| AOD             | H8L3ARP Product                 | 0.05-degree   | `D:/H8_data/H8L3ARP/`           |  
| Land Use        | LC_2015_2024.nc                 | Station-scale | `D:/H8_data/LC_2015_2024.nc`    |  

---

#### 6. Usage Notes  
1. **Station Coverage**: Fixed 2014 stations  
2. **Satellite Transition**:  
   - ≤2022-12-12: Himawari-8  
   - ≥2022-12-13: Himawari-9  
3. **Data Validity**:  
   - `General_availability=0`: Missing input data  
   - `valid_flag=0`: Algorithm failed (reflectance=`NaN`)  
4. **File Generation**:  
   - Skips existing files  
   - Skips processing if inputs missing  
5. **Parallel Processing**: Default workers = CPU cores/2  

> **Processing Log Example**:
> `[2025-07-01 14:30:00] [SUCCESS] Generated SR_20150707_0900.nc - Valid stations: 1800/2014 (89.37%)`

---
*(Document updated: July 1, 2025)*