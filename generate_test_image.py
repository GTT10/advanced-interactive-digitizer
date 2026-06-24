import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# テストデータの生成
x = np.linspace(0, 10, 20)
y1 = np.sin(x)
y2 = np.cos(x)

plt.figure(figsize=(10, 6))
plt.plot(x, y1, 'ro', label='Triangle', marker='^', markersize=10)
plt.plot(x, y2, 'bs', label='Square', marker='s', markersize=10)

plt.legend()
plt.title("Test Plot for Digitizer")
plt.xlabel("X axis")
plt.ylabel("Y axis")
plt.grid(True)

plt.savefig('/home/user/webapp/test_plot.png')
print("Test image saved to /home/user/webapp/test_plot.png")
