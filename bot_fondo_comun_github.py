# bot_fondo_comun_github.py
# Script Unificado para Compra de Divisas en BFC - Versión GitHub Actions
# Incluye notificaciones de Telegram y configuración por variables de entorno

import asyncio
import os
import requests
import pandas as pd
from playwright.async_api import async_playwright, Page, expect

# --- CONFIGURACIÓN DESDE VARIABLES DE ENTORNO (GitHub Secrets/Inputs) ---
URL_LOGIN = "https://www20.bfc.com.ve/" 
URL_COMPRA = "https://www20.bfc.com.ve/main/divisas/compra"

USUARIO = os.getenv("BFC_USUARIO")
CLAVE = os.getenv("BFC_CLAVE")
# El monto se lee de la entrada del usuario en GitHub o del secret por defecto
MONTO_A_COMPRAR = os.getenv("MONTO_A_COMPRAR", "100")

# Telegram Config
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- AJUSTES DE VELOCIDAD ---
TIEMPO_ENTRE_REFRESCOS_SEGUNDOS = 0  # VELOCIDAD MÁXIMA - ni un milisegundo de pausa
NUMERO_DE_INTENTOS_ATAQUE = 20
SELECTOR_BOTON_ACEPTAR = "button:has-text('Aceptar')"
PRIORIDAD_MERCADOS = ["Intervención", "Menudeo"]

# NOTIFICACIONES PERIÓDICAS: Avisar cada 30 min que sigue monitoreando
# (Para confirmar que no se colgó)
INTERVALO_NOTIFICACION_SEGUNDOS = 30 * 60  # 30 minutos

def enviar_telegram(mensaje):
    """Envía una notificación a Telegram si los datos están configurados."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"⚠️ Telegram no configurado. Mensaje: {mensaje}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"🤖 *BFC Bot*:\n{mensaje}",
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"✅ Notificación enviada: {mensaje}")
        else:
            print(f"❌ Error enviando a Telegram: {response.text}")
    except Exception as e:
        print(f"❌ Excepción enviando a Telegram: {e}")

def enviar_documento_telegram(mensaje, ruta_archivo):
    """Envía un archivo (PDF) a Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    try:
        with open(ruta_archivo, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': mensaje, 'parse_mode': 'Markdown'}
            response = requests.post(url, files=files, data=data, timeout=20)
            if response.status_code == 200:
                print(f"✅ Documento enviado: {ruta_archivo}")
            else:
                print(f"❌ Error enviando documento: {response.text}")
    except Exception as e:
        print(f"❌ Excepción enviando documento: {e}")

async def verificar_sesion_activa(page: Page) -> bool:
    try:
        campo_usuario = page.get_by_role("textbox", name="Usuario")
        dropdown_mercado = page.locator('mat-select[formcontrolname="mercado"]')
        
        resultados = await asyncio.gather(
            campo_usuario.is_visible(timeout=1000),
            dropdown_mercado.is_visible(timeout=1000),
            return_exceptions=True
        )
        
        esta_en_login = resultados[0] if not isinstance(resultados[0], Exception) else False
        dropdown_visible = resultados[1] if not isinstance(resultados[1], Exception) else False
        
        if esta_en_login:
            return False
        return dropdown_visible
    except:
        return True

async def login_banco(page: Page):
    """
    Función mejorada de login con:
    - Notificaciones de Telegram en cada paso
    - Navegación directa a URL_COMPRA (salta popup automáticamente)
    - Cierre automático de sesión si falla
    """
    try:
        print("🔐 Iniciando proceso de login...")
        enviar_telegram("🔐 *Iniciando login*\nIntentando acceder al banco...")
        
        await page.goto(URL_LOGIN, timeout=30000)
        
        # PASO 1: Usuario
        print("   → Llenando campo de usuario...")
        usuario_campo = page.get_by_role("textbox", name="Usuario")
        await usuario_campo.wait_for(state="visible", timeout=20000)
        await usuario_campo.fill(USUARIO)
        await page.get_by_role("button", name="Continuar").click()
        
        # PASO 2: Contraseña (con espera más realista)
        print("   → Esperando campo de contraseña...")
        await page.wait_for_timeout(2000)  # Pausa humana
        
        pass_campo = page.get_by_role("textbox", name="Contraseña")
        try:
            await pass_campo.wait_for(state="visible", timeout=15000)
            await pass_campo.fill(CLAVE)
            await page.get_by_role("button", name="Iniciar sesión").click()
        except:
            enviar_telegram("⚠️ *Error crítico*\nNo se encontró el campo de contraseña.\nCerrando sesión...")
            await page.close()
            raise Exception("Campo de contraseña no encontrado - posible detección de bot")
        
        # PASO 3: Esperar a que termine el login y NAVEGAR DIRECTO A COMPRA
        # (Esto salta el popup de bienvenida automáticamente)
        print("   → Esperando confirmación de login...")
        await page.wait_for_timeout(5000)
        
        print("   → Navegando directo a página de compra...")
        await page.goto(URL_COMPRA, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)
        
        # Verificar que estamos en la página de compra
        print("   → Verificando acceso a compra...")
        dropdown = page.locator('mat-select[formcontrolname="mercado"]')
        
        if await dropdown.is_visible(timeout=10000):
            print("✅ Login exitoso - Sesión activa")
            enviar_telegram("✅ *Login exitoso*\nSesión iniciada correctamente.\n🔍 Comenzando monitoreo...")
        else:
            enviar_telegram("❌ *Login falló*\nNo se pudo acceder a la página de compra.\nCerrando...")
            await page.close()
            raise Exception("No se pudo acceder a la página de compra")
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error en login: {error_msg}")
        enviar_telegram(f"🔥 *Error Fatal en Login*\n{error_msg[:100]}\n\nDeteniendo bot...")
        try:
            await page.close()
        except:
            pass
        raise

async def llenar_formulario_intervencion(page: Page):
    print("📝 Llenando formulario de INTERVENCIÓN...")
    campo_monto = page.locator('input[formcontrolname="monto"]')
    await campo_monto.click()
    for caracter in str(MONTO_A_COMPRAR):
        await campo_monto.press(caracter)
        await page.wait_for_timeout(50)
    
    await page.locator('#mat-select-6').click()
    await page.locator('mat-option').first.click()
    await page.locator('#mat-select-8').click()
    await page.locator('mat-option').first.click()
    await page.locator('#mat-select-10').click()
    await page.locator('mat-option').first.click()
    await page.locator('#mat-select-12').click()
    await page.locator('mat-option').first.click()

async def llenar_formulario_menudeo(page: Page):
    print("📝 Llenando formulario de MENUDEO...")
    campo_monto = page.get_by_role("textbox", name="0")
    await campo_monto.click()
    for caracter in str(MONTO_A_COMPRAR):
        await campo_monto.press(caracter)
        await page.wait_for_timeout(50)
    await asyncio.sleep(2)

async def ejecutar_ataque_final(page: Page, mercado: str):
    print(f"💥 Iniciando ráfaga de intentos en {mercado}...")
    enviar_telegram(f"🎯 *Mercado Abierto:* {mercado}\nIniciando compra por {MONTO_A_COMPRAR} USD...")
    
    for i in range(NUMERO_DE_INTENTOS_ATAQUE):
        await page.locator(SELECTOR_BOTON_ACEPTAR).click()
        try:
            boton_confirmar = page.locator('button:has-text("Confirmar")')
            await boton_confirmar.wait_for(state="visible", timeout=3000)
            await boton_confirmar.click(force=True)
            
            # --- CAPTURA DE COMPROBANTE EN PDF (ESPERA INTELIGENTE) ---
            print("⏳ Esperando recibo de compra...")
            try:
                # Esperar hasta 20s a que aparezca algún indicador de éxito
                # Ajusta este texto si sabes exactamente qué dice el recibo (ej: "Referencia", "Exitosa")
                indicador_exito = page.locator("text=Exitosa").or_(page.locator("text=Referencia"))
                await indicador_exito.wait_for(state="visible", timeout=20000)
                print("✅ Recibo detectado. Generando PDF...")
                await page.wait_for_timeout(2000) # Un respiro extra para que renderice bien
            except:
                print("⚠️ No se detectó texto de recibo rápido, generando PDF igual...")
            
            nombre_pdf = "comprobante_compra.pdf"
            await page.pdf(path=nombre_pdf)
            enviar_documento_telegram("📄 *Aquí tienes el comprobante de compra*", nombre_pdf)
            # -------------------------------------

            exito_msj = f"✅ *¡COMPRA EXITOSA!*\n💰 Monto: {MONTO_A_COMPRAR} USD\n🏦 Mercado: {mercado}"
            print(exito_msj)
            enviar_telegram(exito_msj)
            await page.wait_for_timeout(10000)
            return True
        except:
            mensaje_error = page.locator("simple-snack-bar > div > div > button")
            if await mensaje_error.is_visible(timeout=500):
                await mensaje_error.click()
            await page.wait_for_timeout(500)
    
    error_msj = f"❌ *Compra fallida* tras {NUMERO_DE_INTENTOS_ATAQUE} intentos en {mercado}."
    enviar_telegram(error_msj)
    return False

async def main():
    if not USUARIO or not CLAVE:
        print("❌ Faltan credenciales (BFC_USUARIO o BFC_CLAVE)")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) # Headless para GitHub
        context = await browser.new_context()
        page = await context.new_page()

        try:
            print(f"🤖 Iniciando bot para {MONTO_A_COMPRAR} USD...")
            enviar_telegram(f"🚀 *Bot Iniciado*\nVigilando mercados (Monto: {MONTO_A_COMPRAR} USD)")
            
            await login_banco(page)
            
            oportunidad_encontrada = False
            inicio_monitoreo = asyncio.get_event_loop().time()
            ultima_notificacion = inicio_monitoreo
            
            while not oportunidad_encontrada:
                # Notificar cada 30 minutos que sigue monitoreando
                tiempo_actual = asyncio.get_event_loop().time()
                tiempo_desde_ultima_notif = tiempo_actual - ultima_notificacion
                
                if tiempo_desde_ultima_notif >= INTERVALO_NOTIFICACION_SEGUNDOS:
                    horas_monitoreando = int((tiempo_actual - inicio_monitoreo) / 3600)
                    minutos_monitoreando = int(((tiempo_actual - inicio_monitoreo) % 3600) / 60)
                    enviar_telegram(f"🔍 *Sigo vigilando*\nLlevo {horas_monitoreando}h {minutos_monitoreando}m monitoreando.\nMercado aún cerrado. ✅")
                    ultima_notificacion = tiempo_actual
                
                try:
                    await page.goto(URL_COMPRA, wait_until="domcontentloaded", timeout=20000)
                    await page.locator('mat-select[formcontrolname="mercado"]').click()
                    
                    for mercado in PRIORIDAD_MERCADOS:
                        try:
                            opcion_mercado = page.locator('mat-option').filter(has_text=mercado)
                            await opcion_mercado.wait_for(state="visible", timeout=500)
                            
                            await opcion_mercado.click()
                            if mercado == "Intervención":
                                await llenar_formulario_intervencion(page)
                            else:
                                await llenar_formulario_menudeo(page)
                            
                            await ejecutar_ataque_final(page, mercado)
                            oportunidad_encontrada = True
                            break
                        except:
                            continue
                except:
                    sesion_activa = await verificar_sesion_activa(page)
                    if not sesion_activa:
                        enviar_telegram("⚠️ Sesión cerrada. Reconectando...")
                        await login_banco(page)
                
                if not oportunidad_encontrada:
                    await asyncio.sleep(TIEMPO_ENTRE_REFRESCOS_SEGUNDOS)

        except Exception as e:
            error_fatal = f"🔥 *Error Fatal:* {str(e)}"
            print(error_fatal)
            enviar_telegram(error_fatal)
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
