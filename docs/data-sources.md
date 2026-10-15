# Sources, access and claim boundaries

Checked on 14 October 2026. Source statements are provider documentation; acquisition
claims below are backed by local stored metadata and actual HTTP/raster reads.

| Source | Use and access | Licensing / cadence | Verified in this execution |
|---|---|---|---|
| Copernicus Sentinel-2 L2A | Six bands and SCL through the explicit public Element 84 COG mirror. CDSE STAC discovery also supported. | Sentinel legal notice, attribution required; acquisition/revisit and catalogue publication vary. No claim of live, continuous coverage. | CDSE search returned 12 matches; Earth Search discovery and ten actual multispectral observations retrieved (eight historical, two 2025/2026 live analysis). |
| Hansen GFC-2025-v1.13 | Annual gross tree-cover-loss year, treecover2000 and land mask; bounded Google-hosted raster windows. | CC BY 4.0; cite Hansen et al. and University of Maryland GLAD. Annual reference, not current event detection or unbiased area estimates. | Three layers read for each of four regions. |
| NASA FIRMS MODIS C6.1 public NRT | Public rolling 24-hour CSV, 10 MB limit, hourly cache, per-observation UTC time/confidence/sensor/footprint. | NASA open data with product attribution; rolling NRT observations. NRT is not the evaluation science archive. | Official public feed fetched, parsed and hashed. No points in selected Milas AOI in that snapshot. |
| NASA FIRMS keyed VIIRS/MODIS | Authenticated area API, bounded date interval, separately identified SP/NRT source. | MAP_KEY and appropriate archive access; science archive needed for historical labels. | Parser and credential/error gates tested; authenticated acquisition blocked by absent key. |
| ESA WorldCover 2021 v200 | Auxiliary land-cover context; native 10 m map sampled to the analysis grid. | CC BY 4.0. Attribute ESA WorldCover consortium and modified Copernicus data. Annual 2020/2021 products use different algorithms. | 2021 context for Milas actually retrieved and hashed. No 2020/2021 subtraction used. |
| Dynamic World | Potential auxiliary labels and per-class confidence; not independent ecological truth. | CC BY 4.0; Earth Engine access and attribution. | Documentation researched; not acquired or used in training. |
| ERA5-Land / CDS | Optional authenticated retrieval adapter for retrospective covariate research. | Accepted CDS dataset terms and API credentials required. Reanalysis publication time differs from valid time. | No configured credentials; not downloaded. As-of gates reject unverified future/publication timing. |
| EFFIS / ECMWF fire danger | Candidate scientifically established comparison and historical fire context. | Product-specific access/terms; do not redistribute without checking the selected product. | Not acquired or integrated in this release. |
| Esri World Imagery | Attributed browser background only, not model input or assessment source. | Esri/imagery-provider service terms; availability and permitted operational usage require review before a public pilot. | Rendered in local browser. |

Authoritative documentation:

- [Copernicus STAC documentation](https://documentation.dataspace.copernicus.eu/APIs/STAC.html)
- [Element 84 Earth Search](https://element84.com/earth-search/) and [provider repository](https://github.com/Element84/earth-search)
- [Hansen GFC-2025-v1.13 download and usage notes](https://storage.googleapis.com/earthenginepartners-hansen/GFC-2025-v1.13/download.html)
- [NASA FIRMS area API](https://firms.modaps.eosdis.nasa.gov/api/area/) and [public fire data](https://firms.modaps.eosdis.nasa.gov/active_fire/)
- [ESA WorldCover data and licensing](https://esa-worldcover.org/en/data-access)
- [Google Dynamic World dataset](https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1)
- [ERA5-Land documentation](https://confluence.ecmwf.int/pages/viewpage.action?pageId=505384848)
- [EFFIS](https://forest-fire.emergency.copernicus.eu/)

No NASA, ESA, Copernicus, university, NGO or municipality endorsement or collaboration is
claimed. The data are authentic remote observations and algorithmic reference products;
their interpretation still needs independent ecological review.
