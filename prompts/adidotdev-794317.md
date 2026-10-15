# Gemini 4 Argon video by @Adidotdev

[Original post](https://x.com/Adidotdev/status/2110079828531794317)

- **Category:** 3D scenes
- **Built with:** Canvas
- **Author:** [@Adidotdev](https://x.com/Adidotdev)

## Prompt

```text
我要做一个全屏网页交互场景："树脂块微缩岛屿"。参考我上传的参考图，做出一张树脂方块里装着悬崖、沙滩和清澈青绿海水的实拍风格图，要达到那种真实质感；整块像果冻一样跟着鼠标晃，水面随鼠标起浪，水要果冻质感

技术栈：Vite + React + TypeScript，three + @react-three/fiber v9 + @react-three/drei + @react-three/postprocessing，leva 做调参面板。所有 3D 内容全部用代码程序化生成，不加载任何模型文件；环境光用 drei 的 Environment 预设即可。遵循 R3F 和 drei 的官方最佳实践。

场景要有：
- 一个圆角透明树脂块，块体本身就是海水，用 MeshTransmissionMaterial 做出通透感和由浅到深的青绿色水色。
- 块体内部的沙色海床，带焦散光斑，散布几块岩石，部分露出水面。
- 块体顶面的动态水面：GPU 高度场模拟，鼠标划过起涟漪，空闲时也有微弱自然波动；要有反射、浅深水混色和岸边泡沫。
- 一角的程序化岛屿：噪声地形塑出陡峭悬崖和一弯沙滩，按高度和坡度分层着色，缓坡上实例化散布简单几何体做植被。
- 果冻效果：整个场景跟随鼠标位移做弹簧式晃动，块体顶部晃得比底部多。
- 产品摄影式的呈现：米白背景、长焦俯视相机、接触阴影、景深做出微缩感，轻微泛光和暗角。
- leva 面板：水色、浪高、涟漪强度、太阳角度、潮位、果冻软硬、景深。

要求：桌面 60fps，手机 30fps 以上并自动降级；组件按职责拆分，高度场模拟独立成 hook；先跑通整体，再精修材质和参数。
```
