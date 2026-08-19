# Agents

## Виртуальная среда

Единственный интерпретатор: **`myenv\Scripts\python.exe`** (venv в корне репо).
Системный `C:\Python310` не имеет PyQt6 / `pillow_jxl` — не использовать.

## Тесты

После **каждого** изменения запускать полный прогон:

```bash
myenv\Scripts\python.exe -m pytest tests/ -q
```
