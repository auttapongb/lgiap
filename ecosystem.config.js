module.exports = {
  apps: [
    {
      name: 'lgiap-api',
      script: 'backend/main.py',
      interpreter: 'venv/bin/python3',
      cwd: '/data/lgiap',
      env: {
        PYTHONUNBUFFERED: '1'
      }
    },
    {
      name: 'lgiap-worker',
      script: '-m',
      args: 'dramatiq app.tasks.ingest --processes 2',
      interpreter: 'venv/bin/python3',
      cwd: '/data/lgiap/backend',
      env: {
        PYTHONUNBUFFERED: '1'
      }
    }
  ]
}
