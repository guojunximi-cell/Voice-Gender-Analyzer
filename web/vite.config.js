import { defineConfig } from "vite";

export default defineConfig({
	server: {
		// 绑在 IPv6 全零地址，Linux 默认 dual-stack 会同时接 IPv4 连接。
		// 背景：Windows Chrome 的 `localhost` 常优先解析到 ::1，而 Vite
		// 默认只在 127.0.0.1（IPv4）监听，WSL 端口转发也只桥 IPv4 —— 浏览器
		// 直连 [::1]:5173 就命中不到 Vite，DevTools 里能看到 Remote Address
		// 是 [::1]:5173 却拿到一个带 CORS 头的假 404（来自 Windows 侧的代理
		// / 安全软件 / 某个吃掉这个端口的系统组件）。
		// 注：`host: true` 只等价 0.0.0.0，依然 IPv4-only，解不了这个问题。
		host: "::",
		proxy: {
			"/api": {
				target: "http://127.0.0.1:8080",
				changeOrigin: true,
			},
		},
	},
});
