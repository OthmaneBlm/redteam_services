FROM python:3.11-slim AS base
WORKDIR /app

# ---------- Dependencies ----------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------- Copy Source ----------
COPY . /app

# ---------- Expose and Run ----------
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
