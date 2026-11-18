# Parámetros comunes del proxy hacia la API
proxy_pass http://api:8000;
proxy_set_header Host $host;
# Se SOBRESCRIBE (no se agrega) para que el cliente no pueda falsificar su IP
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto https;
proxy_read_timeout 30s;
