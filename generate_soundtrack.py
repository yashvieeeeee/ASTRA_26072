import numpy as np
from scipy.io import wavfile
import os

sr = 44100
duration = 120.0
num_samples = int(sr * duration)
t = np.linspace(0, duration, num_samples, endpoint=False)

# 1. Deep Sub-bass drone (55Hz C1 with 55.5Hz binaural beat and 0.05Hz LFO)
lfo1 = 0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * t)
drone_left = np.sin(2 * np.pi * 55.0 * t) * (0.35 + 0.15 * lfo1)
drone_right = np.sin(2 * np.pi * 55.4 * t) * (0.35 + 0.15 * lfo1)

# Harmonics (110Hz, 165Hz)
harm1 = 0.15 * np.sin(2 * np.pi * 110.0 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.03 * t))
harm2 = 0.08 * np.sin(2 * np.pi * 164.81 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * t))

# 2. Cinematic Chord Swells (C minor: C, Eb, G, Bb, D)
def make_pad(freq, start_sec, dur_sec, attack_sec=3.0, release_sec=3.0, vol=0.1):
    pad = np.zeros(num_samples)
    idx_start = int(start_sec * sr)
    idx_end = min(num_samples, int((start_sec + dur_sec) * sr))
    t_pad = np.linspace(0, dur_sec, idx_end - idx_start, endpoint=False)
    
    # Envelope
    env = np.ones_like(t_pad)
    att_samples = int(attack_sec * sr)
    rel_samples = int(release_sec * sr)
    if att_samples > 0 and att_samples < len(env):
        env[:att_samples] = np.linspace(0, 1, att_samples)
    if rel_samples > 0 and rel_samples < len(env):
        env[-rel_samples:] = np.linspace(1, 0, rel_samples)
        
    sig = vol * np.sin(2 * np.pi * freq * t_pad) * env
    pad[idx_start:idx_end] = sig
    return pad

# Swell 1 (Scene 1-2: 0s-20s) - C min
pad_c3 = make_pad(130.81, 0, 22, 4, 4, 0.08)
pad_eb3 = make_pad(155.56, 2, 20, 5, 4, 0.07)
pad_g3 = make_pad(196.00, 4, 18, 5, 4, 0.07)

# Swell 2 (Scene 3-4: 20s-55s) - Ab maj7
pad_ab3 = make_pad(207.65, 20, 36, 6, 5, 0.09)
pad_c4 = make_pad(261.63, 22, 34, 6, 5, 0.08)
pad_eb4 = make_pad(311.13, 25, 30, 6, 5, 0.07)

# Swell 3 (Scene 5-7: 55s-102s Climax) - F min / C min
pad_f3 = make_pad(174.61, 55, 48, 5, 6, 0.11)
pad_c4_b = make_pad(261.63, 58, 45, 5, 6, 0.10)
pad_g4 = make_pad(392.00, 62, 40, 6, 6, 0.09)
pad_bb4 = make_pad(466.16, 75, 28, 4, 5, 0.08)

# Swell 4 (Scene 8-9: 102s-120s Resolution) - C sus4 -> C maj
pad_c3_end = make_pad(130.81, 100, 20, 3, 5, 0.10)
pad_g3_end = make_pad(196.00, 102, 18, 3, 5, 0.09)
pad_e4_end = make_pad(329.63, 105, 15, 4, 5, 0.09)

pad_total = pad_c3 + pad_eb3 + pad_g3 + pad_ab3 + pad_c4 + pad_eb4 + pad_f3 + pad_c4_b + pad_g4 + pad_bb4 + pad_c3_end + pad_g3_end + pad_e4_end

# 3. Radar Sonar Pings & High Ticks at scene transitions (0s, 10s, 22s, 36s, 56s, 70s, 82s, 102s, 114s)
pings = np.zeros(num_samples)
ping_times = [0.1, 10.0, 22.0, 36.0, 56.0, 70.0, 82.0, 102.0, 114.0]
for pt in ping_times:
    idx = int(pt * sr)
    dur_p = int(0.6 * sr)
    if idx + dur_p < num_samples:
        t_p = np.linspace(0, 0.6, dur_p, endpoint=False)
        # Sine ping at 880Hz (A5) with exponential decay
        ping_sig = 0.12 * np.sin(2 * np.pi * 880 * t_p) * np.exp(-12 * t_p)
        # Soft sub impact
        sub_impact = 0.20 * np.sin(2 * np.pi * 60 * t_p) * np.exp(-8 * t_p)
        pings[idx:idx+dur_p] += ping_sig + sub_impact

# 4. Subtle atmospheric wind/filtered noise sweep
np.random.seed(42)
white_noise = np.random.normal(0, 0.03, num_samples)
# Simple moving average filter for lowpass effect
window_size = 80
kernel = np.ones(window_size) / window_size
filtered_noise = np.convolve(white_noise, kernel, mode='same')
noise_lfo = 0.4 + 0.3 * np.sin(2 * np.pi * 0.04 * t)
noise_sig = filtered_noise * noise_lfo

# Mix Left & Right
left_channel = drone_left + harm1 + pad_total + pings + noise_sig
right_channel = drone_right + harm2 + pad_total + pings + noise_sig

# Normalize audio to -2dB headroom
max_val = max(np.max(np.abs(left_channel)), np.max(np.abs(right_channel)))
if max_val > 0:
    scale = (10 ** (-2.0 / 20.0)) / max_val
    left_channel *= scale
    right_channel *= scale

# Convert 16-bit PCM WAV
stereo_wav = np.vstack((left_channel, right_channel)).T
stereo_pcm = (stereo_wav * 32767).astype(np.int16)

out_dir = r"c:\Users\Yashvie Mahey\OneDrive\Desktop\ASTRA_26072\brag-output\composition"
out_wav = os.path.join(out_dir, "soundtrack.wav")
wavfile.write(out_wav, sr, stereo_pcm)
print(f"Generated soundtrack WAV: {out_wav}")
