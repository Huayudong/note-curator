# 迁移

## 旧画像迁移

旧画像按目录名存放、未隔离 vault 与语言。迁移：

```bash
python scripts/migrate_profiles.py            # 预览迁移计划
python scripts/migrate_profiles.py --apply    # 执行
```

- 新目录命名为 `<目录名>-<语言>`，注入 profile_key（用户 + vault_id + 语言）；
- **旧目录原样保留**：删除新目录即回退；
- 同名冲突自动加 vault 前缀；已迁移过的旧目录不会重复出计划。

## vault 搬家

```bash
python scripts/migrate_profiles.py --relink "旧路径" "新路径"
```

把旧路径登记的 vault_id 关联到新路径（旧映射保留），已学习的改稿证据
继续有效。

## 换电脑

1. 复制 `~/.note-curator/`（跳过 `config.yaml`，重新 init 或编辑 vault_path）；
2. 迁移画像（如上）；
3. `preferences.py export/import` 可单独迁移偏好（不含原文证据）。

## 兼容矩阵

由更新版本写入者创建的状态文件会被旧版本拒绝（`E-SCHEMA-NEW`），
先升级插件再使用；schema 上限见 `scripts/nc_core.py` 的 `SCHEMA_MAX`。
