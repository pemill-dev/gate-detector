# Guia de Troubleshooting e Testes

## Testes Locais Antes do Deploy

Antes de fazer o deploy no Coolify, você pode testar a solução localmente (em um computador com Docker instalado) para garantir que tudo funciona corretamente.

### Teste 1: Verificar Conectividade com a DVR

```bash
# Testar ping na DVR
ping 192.168.0.21

# Testar conexão HTTP na porta 80
curl -u manus:Teste123 http://192.168.0.21/
```

Se ambos os comandos funcionarem, a conectividade básica está OK.

### Teste 2: Construir a Imagem Docker Localmente

```bash
# Navegar até o diretório com os arquivos
cd /caminho/para/arquivos

# Construir a imagem
docker build -t gate-detector:latest .

# Verificar se a imagem foi criada
docker images | grep gate-detector
```

### Teste 3: Executar o Container Localmente

```bash
# Executar o container com as variáveis de ambiente
docker run -it \
  -e DVR_HOST=192.168.0.21 \
  -e DVR_PORT=80 \
  -e DVR_USER=manus \
  -e DVR_PASS=Teste123 \
  -e CAMERA_INDEX=2 \
  -e GATE_API_URL=http://api-v2.pemill.com.br/open/dor/2 \
  -v $(pwd)/logs:/app/logs \
  gate-detector:latest
```

Observe os logs. Se tudo estiver funcionando:
- Você verá "Stream de vídeo inicializado com sucesso"
- Você verá "Modelo YOLOv8 carregado com sucesso"
- Você verá "Sistema pronto. Monitorando câmera..."

### Teste 4: Usar Docker Compose Localmente

```bash
# Copiar o arquivo de exemplo
cp .env.example .env

# Editar o .env com suas configurações (se necessário)
nano .env

# Executar com docker-compose
docker-compose up -d

# Ver logs em tempo real
docker-compose logs -f

# Parar o container
docker-compose down
```

## Problemas Comuns e Soluções

### Problema: "Falha ao abrir stream de vídeo"

**Causa**: O sistema não consegue conectar ao stream RTSP da DVR.

**Soluções**:
1. Verifique se o IP da DVR está correto: `ping 192.168.0.21`
2. Verifique se a porta está correta (geralmente 80 para HTTP ou 554 para RTSP)
3. Verifique as credenciais (usuário e senha)
4. Certifique-se de que o protocolo ONVIF está ativado nas configurações da DVR
5. Tente acessar a interface web da DVR diretamente: `http://192.168.0.21`

### Problema: "Erro ao obter stream via ONVIF"

**Causa**: A biblioteca ONVIF não consegue se conectar ou obter as informações de stream.

**Soluções**:
1. Verifique se a DVR suporta ONVIF (a iMHDX 3132 suporta)
2. Tente aumentar o timeout da conexão
3. Verifique se há firewall bloqueando a comunicação ONVIF (porta 8080 ou similar)
4. O sistema usará automaticamente a URL de fallback se o ONVIF falhar

### Problema: "Timeout ao enviar requisição para abrir portão"

**Causa**: A API da Pemill não está respondendo ou há problema de conectividade.

**Soluções**:
1. Verifique se a URL está correta: `http://api-v2.pemill.com.br/open/dor/2`
2. Teste a API manualmente:
   ```bash
   curl -X POST http://api-v2.pemill.com.br/open/dor/2 \
     -H "Content-Type: application/json" \
     -d '{"action": "open"}'
   ```
3. Verifique se há firewall bloqueando a saída para a internet
4. Verifique se a API realmente está respondendo (pode estar em manutenção)

### Problema: "Portão abrindo constantemente"

**Causa**: O sistema está detectando carros continuamente e abrindo o portão a cada detecção.

**Soluções**:
1. Aumente o `GATE_COOLDOWN_SECONDS` para um valor maior (ex: 120 segundos)
2. Aumente o `CONFIDENCE_THRESHOLD` para reduzir falsos positivos (ex: 0.6 ou 0.7)
3. Verifique se há objetos na câmera que se parecem com carros (sombras, reflexos, etc.)

### Problema: "Não está detectando carros"

**Causa**: O modelo YOLOv8 não está reconhecendo os carros.

**Soluções**:
1. Diminua o `CONFIDENCE_THRESHOLD` para um valor menor (ex: 0.3 ou 0.4)
2. Verifique a qualidade do stream de vídeo (pode estar muito pixelizado)
3. Verifique se há iluminação suficiente na câmera
4. Teste com um vídeo de teste local para verificar se o modelo funciona

### Problema: "Alto uso de CPU/Memória"

**Causa**: O processamento de vídeo com IA consome muitos recursos.

**Soluções**:
1. O modelo YOLOv8 nano já é o mais otimizado. Não há versão menor.
2. Reduza a resolução do stream (se possível, na DVR)
3. Reduza a taxa de frames processados (modificar o código para pular frames)
4. Aumente os limites de recursos no `docker-compose.yml` se o servidor tiver capacidade

## Monitoramento em Produção

### Verificar Status do Container

```bash
# Se usando docker-compose
docker-compose ps

# Se usando Docker diretamente
docker ps | grep gate-detector
```

### Ver Logs

```bash
# Últimas 100 linhas de log
docker-compose logs --tail=100

# Logs em tempo real
docker-compose logs -f

# Logs de um dia específico
docker-compose logs --since 2024-01-15
```

### Reiniciar o Container

```bash
# Se usando docker-compose
docker-compose restart

# Se usando Docker diretamente
docker restart gate-detector
```

### Atualizar a Imagem

```bash
# Reconstruir a imagem
docker-compose build --no-cache

# Reiniciar com a nova imagem
docker-compose up -d
```

## Métricas Esperadas

Quando o sistema está funcionando corretamente, você deve observar:

- **FPS (Frames Per Second)**: Entre 5-15 FPS, dependendo da resolução do stream e poder de processamento
- **Latência de Detecção**: Geralmente menos de 1 segundo entre a detecção de um carro e o envio da requisição
- **Uso de CPU**: Entre 30-80% de um núcleo (dependendo do modelo de CPU)
- **Uso de Memória**: Entre 500MB-1.5GB

Se os valores estiverem muito acima disso, há algo errado ou o servidor está sobrecarregado.

## Suporte e Contato

Se você encontrar problemas não listados aqui, verifique:
1. Os logs do container (`docker-compose logs`)
2. A conectividade de rede (`ping`, `curl`)
3. As credenciais da DVR
4. A documentação do Coolify
