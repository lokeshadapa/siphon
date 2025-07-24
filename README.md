# Siphon

## Setup

### Prerequisites
```bash
- Docker
- Your OpenAI API key
```

### Installation
```bash
git clone https://github.com/lokeshadapa/siphon.git
cd siphon
docker build -t siphon .
```

## How to Run Locally

### Quick Start
```bash
docker run -e OPENAI_API_KEY="your-api-key" siphon
```

### With Data Persistence
```bash
mkdir -p ./data
docker run -e OPENAI_API_KEY="your-api-key" -v $(pwd)/data:/code/data siphon
```

### Without Docker
```bash
python main.py
```

## Link to Daily Job Logs
**Live Logs**: http://128.199.14.76:8080/siphon-cron.log

- **Schedule**: Daily at 5:15 AM UTC
- **Server**: DigitalOcean Droplet (128.199.14.76)

## Screen Shots
- https://github.com/lokeshadapa/siphon/tree/main/screenshots-gpt-4o-mini

## GPT Model Comparison
- https://github.com/lokeshadapa/siphon/blob/main/model%20comparison.md
---

