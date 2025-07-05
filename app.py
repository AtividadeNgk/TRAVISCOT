from flask import Flask, jsonify, request, send_file, session, redirect, url_for
import modules.manager as manager
import asyncio, json, requests, datetime, time
import mercadopago, os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from multiprocessing import Process
from bot import run_bot_sync

# Configurações do Mercado Pago
CLIENT_ID = os.environ.get("CLIENT_ID", "4714763730515747")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "i33hQ8VZ11pYH1I3xMEMECphRJjT0CiP")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", 'kekel')

# Carrega configurações
try:
    config = json.loads(open('./config.json', 'r').read())
except:
    config = {}

# Usa variáveis de ambiente com fallback para config.json
IP_DA_VPS = os.environ.get("URL", config.get("url", "https://localhost:4040"))
REGISTRO_TOKEN = os.environ.get("REGISTRO_TOKEN", config.get("registro", ""))
ADMIN_PASSWORD = os.environ.get("PASSWORD", config.get("password", "adminadmin"))

# Porta do Railway ou padrão
port = int(os.environ.get("PORT", 4040))

dashboard_data = {
    "botsActive": 0,
    "usersCount": 0,
    "salesCount": 0
}

bots_data = {}
processes = {}
tokens = []
event_loop = asyncio.new_event_loop()

def initialize_all_registered_bots():
    """Inicializa todos os bots registrados e ativos."""
    print('Inicializando bots registrados...')
    global bots_data, processes
    bots = manager.get_all_bots()
    print(f'Encontrados {len(bots)} bots')
    
    for bot in bots:
        bot_id = bot[0]

        # Verifica se já existe um processo rodando para este bot
        if str(bot_id) in processes and processes[str(bot_id)].is_alive():
            print(f"Bot {bot_id} já está em execução. Ignorando nova inicialização.")
            continue

        try:
            start_bot(bot[1], bot_id)
            print(f"Bot {bot_id} iniciado com sucesso.")
            
            # CORREÇÃO: Garante que o bot_id seja string no dicionário processes
            if str(bot_id) not in processes and bot_id in processes:
                processes[str(bot_id)] = processes[bot_id]
                processes.pop(bot_id)
            
        except Exception as e:
            print(f"Erro ao iniciar o bot {bot_id}: {e}")
    
    # Aguarda um pouco para garantir que todos os bots iniciaram
    time.sleep(2)
    
    # Inicia disparos programados para todos os bots
    print('Inicializando disparos programados...')
    bots_with_broadcasts = manager.get_all_bots_with_scheduled_broadcasts()
    print(f'Encontrados {len(bots_with_broadcasts)} bots com disparos programados')
    
    # Nota: Os disparos serão iniciados individualmente por cada bot quando ele iniciar

@app.route('/callback', methods=['GET'])
def callback():
    """
    Endpoint para receber o webhook de redirecionamento do Mercado Pago.
    """
    TOKEN_URL = "https://api.mercadopago.com/oauth/token"

    authorization_code = request.args.get('code')
    bot_id = request.args.get('state')

    if not authorization_code:
        return jsonify({"error": "Authorization code not provided"}), 400

    try:
        payload = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": authorization_code,
            "redirect_uri": IP_DA_VPS+'/callback',
            "state":bot_id,
        }
        
        response = requests.post(TOKEN_URL, data=payload)
        response_data = response.json()

        if response.status_code == 200:
            access_token = response_data.get("access_token")
            print(f"Token MP recebido para bot {bot_id}")
            manager.update_bot_gateway(bot_id, {'type':"MP", 'token':access_token})
            return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Token Cadastrado</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f4f4f9;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            color: #333;
        }
        .container {
            background-color: #fff;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
            border-radius: 8px;
            padding: 20px 30px;
            text-align: center;
            max-width: 400px;
        }
        .container h1 {
            color: #4caf50;
            font-size: 24px;
            margin-bottom: 10px;
        }
        .container p {
            font-size: 16px;
            margin-bottom: 20px;
        }
        .btn {
            display: inline-block;
            padding: 10px 20px;
            font-size: 14px;
            color: #fff;
            background-color: #4caf50;
            text-decoration: none;
            border-radius: 4px;
            transition: background-color 0.3s ease;
        }
        .btn:hover {
            background-color: #45a049;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Token Cadastrado com Sucesso!</h1>
        <p>O seu token Mercado Pago está pronto para uso.</p>
    </div>
</body>
</html>
"""
        else:
            return jsonify({"error": response_data}), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/mp', methods=['POST'])
def handle_webhook():
    data = request.get_json(silent=True)
    print(f"Webhook MP recebido: {data}")
    
    if data and data.get('type') == 'payment':
        transaction_id = (data.get('data').get('id'))
        print(f'Pagamento {transaction_id} recebido - Mercado Pago')
        payment = manager.get_payment_by_trans_id(transaction_id)
        
        if payment:
            print(payment)
            bot_id = json.loads(payment[4])
            token = manager.get_bot_gateway(bot_id)
            sdk = mercadopago.SDK(token['token'])
            pagamento = sdk.payment().get(transaction_id)
            pagamento_status = pagamento["response"]["status"]

            if pagamento_status == "approved":
                print(f'Pagamento {transaction_id} aprovado - Mercado Pago')
                manager.update_payment_status(transaction_id, 'paid')
                return jsonify({"message": "Webhook recebido com sucesso."}), 200
    
    return jsonify({"message": "Evento ignorado."}), 400

@app.route('/webhook/pp', methods=['POST'])
def webhook():
    if request.content_type == 'application/json':
        data = request.get_json()
    elif request.content_type == 'application/x-www-form-urlencoded':
        data = request.form.to_dict()
    else:
        print("[ERRO] Tipo de conteúdo não suportado")
        return jsonify({"error": "Unsupported Media Type"}), 415

    if not data:
        print("[ERRO] Dados JSON ou Form Data inválidos")
        return jsonify({"error": "Invalid JSON or Form Data"}), 400
    
    print(f"[DEBUG] Webhook PP recebido: {data}")
    transaction_id = data.get("id", "").lower()
    
    if data.get('status', '').lower() == 'paid':
        print(f'Pagamento {transaction_id} pago - PushinPay')
        manager.update_payment_status(transaction_id, 'paid')
    else:
        print(f"[ERRO] Status do pagamento não é 'paid': {data.get('status')}")

    return jsonify({"status": "success"})

@app.route('/', methods=['GET'])
def home():
    if session.get("auth", False):
        dashboard_data['botsActive'] = manager.count_bots()
        dashboard_data['usersCount'] = '?'
        dashboard_data['salesCount'] = len(manager.get_all_payments_by_status('finished'))
        return send_file('./templates/terminal.html')
    return redirect(url_for('login'))

@app.route('/visualizar', methods=['GET'])
def view():
    if session.get("auth", False):
        return send_file('./templates/bots.html')
    return redirect(url_for('login'))

@app.route('/delete/<id>', methods=['DELETE'])
async def delete(id):
    if session.get("auth", False):
        # Remove apenas o processo e dados em memória
        if id in processes.keys():
            processes.pop(id)
        if id in bots_data:
            bots_data.pop(id)
        
        # Remove completamente do banco
        manager.delete_bot(id)
        return 'true'
    else:
        return 'Unauthorized', 403

@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        password = request.form['password']
        if password == ADMIN_PASSWORD:
            session['auth'] = True
            return redirect('/')
    return '''
        <form method="post">
            <p><input type="text" name="password" placeholder="Digite a senha"></p>
            <p><input type="submit" value="Entrar"></p>
        </form>
    '''

def start_bot(new_token, bot_id):
    """Inicia um novo bot em um processo separado."""
    bot_id = str(bot_id)  # ESTA LINHA JÁ EXISTE
    if not bot_id in processes.keys():
        process = Process(target=run_bot_sync, args=(new_token, bot_id))
        process.start()
        tokens.append(new_token)
        bot = manager.get_bot_by_id(bot_id)
        bot_details = manager.check_bot_token(new_token)
        bot_obj = {
            'id': bot_id,
            'url':f'https://t.me/{bot_details['result'].get('username', "INDEFINIDO")}' if bot_details else 'Token Inválido',
            'token': bot[1],
            'owner': bot[2],
            'data': json.loads(bot[4])
        }
        bots_data[bot_id] = bot_obj
        processes[bot_id] = process  # bot_id já é string aqui
        print(f"Bot {bot_id} processo iniciado - PID: {process.pid}")
        return True

async def receive_token_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_token = update.message.text.strip()
    admin_id = update.effective_user.id
    
    if manager.bot_exists(new_token):
        await update.message.reply_text('Token já registrado no sistema.')
    else:
        telegram_bot = manager.check_bot_token(new_token)
        if telegram_bot:
            print(f'Novo BOT registrado: {telegram_bot}')
            id = telegram_bot.get('result', {}).get('id', False)
            if id:
                bot = manager.create_bot(str(id), new_token, admin_id)
                start_bot(new_token, id)
                await update.message.reply_text(f'Bot t.me/{telegram_bot['result']['username']} registrado e iniciado. Apenas você pode gerenciá-lo.')
            else:
                await update.message.reply_text('Erro ao obter ID do bot.')
        else:
            await update.message.reply_text('O token inserido é inválido.')
    return ConversationHandler.END

async def start_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Envie seu token')
    return ConversationHandler.END

def main():
    """Função principal para rodar o bot de registro"""
    if not REGISTRO_TOKEN:
        print("Token de registro não configurado!")
        return
        
    registro_token = REGISTRO_TOKEN
    application = Application.builder().token(registro_token).build()
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_token_register))
    application.add_handler(CommandHandler('start', start_func))
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print('Iniciando BOT de Registro')
    application.run_polling()

def start_register():
    register = Process(target=main)
    register.start()

@app.route('/dashboard-data', methods=['GET'])
def get_dashboard_data():
    if session.get("auth", False):
        dashboard_data['botsActive'] = len(processes)
        dashboard_data['usersCount'] = '?'
        dashboard_data['salesCount'] = len(manager.get_all_payments_by_status('finished'))
        return jsonify(dashboard_data)
    return jsonify({"error": "Unauthorized"}), 403

@app.route('/bots', methods=['GET'])
def bots():
    if session.get("auth", False):
        bot_list = manager.get_all_bots()
        bots = []

        for bot in bot_list:
            bot_details = manager.check_bot_token(bot[1])
            bot_structure = {
                'id': bot[0],
                'token': bot[1],
                'url': "Token Inválido",
                'owner': bot[2],
                'data': json.loads(bot[3])
            }
            if bot_details:
                bot_structure['url'] = f'https://t.me/{bot_details['result'].get('username', "INDEFINIDO")}'
            
            bots_data[str(bot[0])] = bot_structure
            bots.append(bot_structure)
        return jsonify(bots)
    return jsonify({"error": "Unauthorized"}), 403

@app.route('/terminal', methods=['POST'])
def terminal():
    if session.get("auth", False):
        data = request.get_json()
        command = data.get('command', '').strip()
        if not command:
            return jsonify({"response": "Comando vazio. Digite algo para enviar."}), 400
        
        response = f"Comando '{command}' recebido com sucesso. Processado às {time.strftime('%H:%M:%S')}."
        return jsonify({"response": response})
    return jsonify({"error": "Unauthorized"}), 403

@app.route('/health', methods=['GET'])
def health():
    """Endpoint de health check para o Railway"""
    return jsonify({
        "status": "healthy",
        "bots_active": len(processes),
        "timestamp": datetime.datetime.now().isoformat()
    })
    
@app.route('/admin/bots', methods=['GET'])
def admin_bots():
    if session.get("auth", False):
        return send_file('./templates/admin_bots.html')
    return redirect(url_for('login'))

@app.route('/api/bots/active', methods=['GET'])
def get_active_bots():
    if session.get("auth", False):
        # Retorna bots ativos com status dos processos
        active_bots = []
        all_bots = manager.get_all_bots()
        
        for bot in all_bots:
            bot_id = str(bot[0])
            bot_token = bot[1]
            
            bot_info = {
                'id': bot_id,
                'token': bot_token,
                'owner': bot[2],
                'status': 'inactive',  # Default
                'username': 'Carregando...'
            }
            
            # Verifica se o processo está ativo
            if bot_id in processes:
                if processes[bot_id] and processes[bot_id].is_alive():
                    bot_info['status'] = 'active'
                else:
                    bot_info['status'] = 'inactive'
            
            # Tenta pegar username do bot
            try:
                bot_details = manager.check_bot_token(bot_token)
                if bot_details and bot_details.get('result'):
                    bot_info['username'] = bot_details['result'].get('username', 'INDEFINIDO')
            except:
                bot_info['username'] = 'Token Inválido'
            
            active_bots.append(bot_info)
        
        return jsonify(active_bots)
    return jsonify({"error": "Unauthorized"}), 403

@app.route('/api/bot/ban/<bot_id>', methods=['POST'])
def ban_bot(bot_id):
    if session.get("auth", False):
        bot = manager.get_bot_by_id(bot_id)
        if bot:
            bot_token = bot[1]
            
            # 1. Para o processo do bot se estiver rodando
            if str(bot_id) in processes:
                try:
                    process = processes[str(bot_id)]
                    if process:
                        # Envia SIGTERM
                        process.terminate()
                        time.sleep(0.5)
                        
                        # Se ainda estiver vivo, SIGKILL
                        if process.is_alive():
                            process.kill()
                            time.sleep(0.5)
                        
                        # Aguarda o processo realmente terminar
                        process.join(timeout=2)
                    
                    # Remove do dicionário de processos
                    processes.pop(str(bot_id))
                    print(f"Processo {bot_id} parado com sucesso")
                except Exception as e:
                    print(f"Erro ao parar processo: {e}")
            
            # 2. Remove dos dados em memória
            if str(bot_id) in bots_data:
                bots_data.pop(str(bot_id))
            
            # 3. Deleta do banco de dados
            success = manager.delete_bot(bot_id)
            
            if success:
                return jsonify({
                    "success": True, 
                    "message": f"Bot {bot_id} banido e removido com sucesso!"
                })
            else:
                return jsonify({
                    "success": False,
                    "message": "Erro ao remover bot do banco de dados"
                }), 500
        
        return jsonify({"error": "Bot não encontrado"}), 404
    return jsonify({"error": "Unauthorized"}), 403

if __name__ == '__main__':
    print(f"Iniciando aplicação na porta {port}")
    print(f"URL configurada: {IP_DA_VPS}")
    
    manager.inicialize_database()
    manager.create_recovery_tracking_table()
    initialize_all_registered_bots()
    start_register()
    
    app.run(debug=False, host='0.0.0.0', port=port)