.PHONY: help all backend frontend stop install clean

# 第一个 target 是 help
help:
	@echo "Nexa Agent V0"
	@echo ""
	@echo "用法: make <target>"
	@echo ""
	@echo "启动:"
	@echo "  all        一键启动前后端"
	@echo "  backend    仅启动后端 (:8000)"
	@echo "  frontend   仅启动前端 (:8501)"
	@echo ""
	@echo "管理:"
	@echo "  install    安装 Python 依赖"
	@echo "  stop       停止两端进程"
	@echo "  clean      清理 data/ logs/ __pycache__"
	@echo ""
	@echo "默认 target: make = make all"

all:
	@echo "启动 Nexa Agent..."
	@echo "  后端 → http://localhost:8000/docs"
	@echo "  前端 → http://localhost:8501"
	@echo ""
	@trap 'kill 0' EXIT; \
		python -m app.main & \
		sleep 2 && streamlit run app/streamlit_app.py & \
		wait

# 仅后端
backend:
	python -m app.main

# 仅前端
frontend:
	streamlit run app/streamlit_app.py

# 安装依赖
install:
	pip install -r requirements.txt

# 停止
stop:
	@lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	@lsof -ti:8501 | xargs kill -9 2>/dev/null || true
	@echo "已停止 :8000 :8501"

# 清理
clean:
	rm -rf data/ logs/ __pycache__ app/__pycache__ app/*/__pycache__
	@echo "已清理 data/ logs/ __pycache__"
