import os
import tensorflow as tf
from tensorflow.keras.models import load_model

# 1. 检查文件路径
model_path = 'interspeech2023_cvfr.hdf5'

print("--- 开始环境检查 ---")
if os.path.exists(model_path):
    print(f"✅ 找到模型文件: {model_path}")
else:
    print(f"❌ 错误：在当前目录下找不到 {model_path}")
    print(f"当前运行目录是: {os.getcwd()}")
    exit()

# 2. 尝试加载模型
print("\n--- 正在尝试加载模型 (这可能需要几秒钟) ---")
try:
    # 注意：该模型可能包含自定义层，这里先尝试标准加载
    model = load_model(model_path, compile=False)
    print("✅ 模型加载成功！")
    
    # 3. 打印模型基本信息
    print("\n--- 模型简报 ---")
    model.summary()
    
    print("\n[结果]: 模型验证通过，可以进行下一步数据处理了。")

except Exception as e:
    print(f"❌ 加载失败。错误信息如下：\n{str(e)}")
    print("\n提示：如果是版本兼容问题，可能需要检查 tensorflow 的版本。")