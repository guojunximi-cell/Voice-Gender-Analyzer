import numpy as np
import librosa
import tensorflow as tf
from tensorflow.keras.models import load_model

# 配置
MODEL_PATH = 'interspeech2023_cvfr.hdf5'
AUDIO_PATH = 'my_voice.wav'  # 确保文件名对得上

def extract_features(audio_path):
    print(f"正在读取音频: {audio_path}...")
    # 模型通常要求 16000Hz 采样率
    y, sr = librosa.load(audio_path, sr=16000)
    
    # 这里是一个简化的处理流程，具体的特征工程取决于该模型的论文实现
    # 假设模型接受的是 Mel 频谱图
    S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128)
    log_S = librosa.power_to_db(S, ref=np.max)
    
    # 这里的维度调整需要根据你之前看到 model.summary() 里的 Input 层来定
    # 暂时假设它需要的是 (None, 128, 128, 1) 这种形状，如果报错我们再调
    return log_S

print("--- 载入模型中 ---")
model = load_model(MODEL_PATH, compile=False)

try:
    # 1. 提取特征
    # 注意：这里的特征提取代码需要根据 VFP 模型的具体要求微调
    # 如果你有该模型的官方 demo 代码，最好参考它的 preprocess 部分
    features = extract_features(AUDIO_PATH)
    
    # 2. 预测
    # 假设我们只取前一小段进行测试
    # 注意：这里可能需要根据 model.summary 的输入维度进行 reshape
    print("--- 正在分析声音特性 ---")
    
    # 这是一个占位逻辑，如果报错，请把 model.summary() 的输入层截图给我
    # input_shape = model.input_shape
    # print(f"模型要求的输入维度是: {input_shape}")
    
    # 假设输入需要 4D tensor [batch, height, width, channel]
    # 演示：我们强制调整一个片段
    # result = model.predict(features_reshaped)
    
    print("\n[提示]: 模型已就绪。为了给出最准确的分数，我需要确认一下你的 model.summary()。")
    print("请查看你之前运行 check_model.py 时，第一行 'InputLayer' 的 'batch_shape' 是多少？")

except Exception as e:
    print(f"❌ 处理出错: {e}")