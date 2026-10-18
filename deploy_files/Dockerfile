# Hugging Face Spaces (Docker) 용 — 근무표 자동 생성기 (폰에서 보기·생성)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul

# Spaces는 uid 1000 사용자로 실행된다 — 이력 폴더에 쓸 수 있게 소유권을 맞춘다
RUN useradd -m -u 1000 user
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY --chown=user . .
USER user

EXPOSE 7860
CMD ["streamlit", "run", "app.py", \
     "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true", \
     "--server.enableCORS=false", "--server.enableXsrfProtection=false", \
     "--browser.gatherUsageStats=false"]
