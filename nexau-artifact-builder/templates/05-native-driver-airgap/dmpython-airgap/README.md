# dmPython 离线安装包

`nexau.json` 的 setup 阶段会用 `uv pip install --no-index --find-links` 从这个目录装 dmPython，所以打包前**必须先把 whl 下载到这里**。

在 NAC runtime 里，这个目录会位于 `/agent/dmpython-airgap/`。其中 `/agent` 是平台 artifact root，也就是上传 zip 后包含 `nexau.json` 的那一层，不是本地机器上的绝对路径。

## 拉 whl

```bash
bash download-whls.sh
```

会从 PyPI 下载两个 wheel（共 ~22 MB）：

- `dmpython-2.5.32-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`（生产 NAC）
- `dmpython-2.5.32-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.whl`（ARM Linux / 鲲鹏服务器）

`uv pip install --find-links` 会按 pod 架构自动挑，两份共存零冲突。

## 仓库不入库

whl 文件已加进 `.gitignore`，每次 clone 仓库后都要重跑一次 `download-whls.sh`。

## 已知问题

dmPython 2.5.x 的 `[CODE:-70089] Encryption module failed to load` 已在 `custom_tools/dameng_sql.py` 的 `_preload_dmssl_libs()` 里自动修，详见 `../TEMPLATE.md` 的「关键设计要点」。
