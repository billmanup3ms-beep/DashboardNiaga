from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import json
import os
import re
import subprocess
import sys
import time

# Ensure real-time stdout streaming when invoked from web dashboard
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

try:
    from pywinauto.application import Application
except ImportError:
    Application = None

try:
    import pyperclip
except ImportError:
    pyperclip = None

# ==============================================================================
# SCRIPT UTUH: FULL INTEGRATION + HANDLE SAVE POPUP + TOKEN (VERSION 19)
# ==============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)


def _load_dotenv():
    env_path = os.path.join(PROJECT_DIR, ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as ef:
        for line in ef:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

DEFAULT_TOKEN_PATH = os.environ.get(
    "USER_TOKEN_PATH", os.path.join(SCRIPT_DIR, "user_token.json")
)
LEGACY_BOT_DIR = r"D:\BOT"
ENKRIPSI_EXE_PATH = os.environ.get(
    "ENKRIPSI_EXE_PATH", r"D:\BOT\Enkripsi_AP2T.exe"
)
IAM_USERNAME = os.environ.get("IAM_USERNAME", "")
IAM_PASSWORD = os.environ.get("IAM_PASSWORD", "")
WEBMAIL_PASSWORD = os.environ.get("WEBMAIL_PASSWORD", "")


def save_token_json(token_info):
    """Simpan user_token.json ke direktori scripts/ dan (jika ada) D:/BOT/."""
    targets = [DEFAULT_TOKEN_PATH]
    legacy_path = os.path.join(LEGACY_BOT_DIR, "user_token.json")
    if os.path.isdir(LEGACY_BOT_DIR) and os.path.abspath(legacy_path) != os.path.abspath(DEFAULT_TOKEN_PATH):
        targets.append(legacy_path)

    for path in targets:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as tf:
            json.dump(token_info, tf, indent=4)
        print(f"[UAT] Token disimpan ke: {path}")


def handle_save_popup(driver):
    """Fungsi pembantu untuk mengabaikan pop-up simpan password jika muncul."""
    try:
        ok_btn = WebDriverWait(driver, 2).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains(translate(text(), 'OKYES', 'okyes'), 'ok') or"
                " contains(translate(text(), 'OKYES', 'okyes'), 'yes')]",
            ))
        )
        ok_btn.click()
        print("Pop-up penyimpanan berhasil di-dismiss dengan tombol OK/Yes.")
    except Exception:
        try:
            alert = driver.switch_to.alert
            alert.accept()
            print("Alert JS berhasil di-accept.")
        except Exception:
            pass


def main():
    print("=" * 70)
    print("[UAT] Memulai proses pengambilan User Token Bearer New AP2T...")
    print("=" * 70)

    options = webdriver.ChromeOptions()
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=options)

    try:
        wait = WebDriverWait(driver, 15)

        # -------------------------------------------------------------
        # LANGKAH 1: BUKA NEW AP2T TERLEBIH DAHULU & KLIK "LOGIN SSO"
        # -------------------------------------------------------------
        driver.get("http://newap2t.pln.co.id/crm/")
        time.sleep(3)

        login_sso_btn = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains(translate(., 'LOGINSSO', 'loginss0'), 'login sso')"
                " or contains(translate(., 'SSO', 'sso'), 'sso')]",
            ))
        )
        login_sso_btn.click()
        print("Tombol Login SSO di New AP2T diklik, diarahkan ke IAM PLN.")
        time.sleep(3)

        ap2t_window = driver.current_window_handle

        # -------------------------------------------------------------
        # LANGKAH 2: DI HALAMAN IAM PLN, LOGIN & MINTA OTP
        # -------------------------------------------------------------
        username_input = wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'input[type="text"], input[name*="user"], input')
            )
        )
        username_input.clear()
        username_input.send_keys(IAM_USERNAME)

        password_input = driver.find_element(
            By.CSS_SELECTOR, 'input[type="password"]'
        )
        password_input.clear()
        password_input.send_keys(IAM_PASSWORD)

        sign_in_btn = wait.until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//button[contains(translate(text(), 'SIGNIN', 'signin'), 'sign"
                " in') or contains(translate(text(), 'SIGNIN', 'signin'),"
                " 'signin')] | //input[@type='submit' and"
                " (contains(translate(@value, 'SIGNIN', 'signin'), 'sign in')"
                " or contains(translate(@value, 'SIGNIN', 'signin'),"
                " 'signin'))]",
            ))
        )
        sign_in_btn.click()
        print("Tombol Sign In IAM diklik.")
        time.sleep(3)

        try:
            gunakan_cara_lain_btn = wait.until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//*[contains(translate(text(), 'GUNAKANCARALAIN',"
                    " 'gunakancaralain'), 'gunakan cara lain')]",
                ))
            )
            gunakan_cara_lain_btn.click()
            print('Link "Gunakan Cara Lain" diklik.')
        except Exception:
            print('Link "Gunakan Cara Lain" tidak ditemukan atau sudah terlewati, melanjutkan...')
        time.sleep(2)

        try:
            kirim_btn = wait.until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//button[contains(translate(text(), 'KIRIM', 'kirim'),"
                    " 'kirim')] | //input[@type='submit' and"
                    " contains(translate(@value, 'KIRIM', 'kirim'), 'kirim')]",
                ))
            )
            kirim_btn.click()
            print("OTP dikirim. Membuka Webmail di Tab Baru...")
        except Exception:
            print("Tombol Kirim OTP tidak ditemukan, melewati...")

        # -------------------------------------------------------------
        # LANGKAH 3: LOGIN WEBMAIL OWA DI TAB BARU & AMBIL OTP
        # -------------------------------------------------------------
        driver.execute_script(
            "window.open('https://webmail.pln.co.id/owa/#path=/mail');"
        )
        time.sleep(2)

        windows = driver.window_handles
        webmail_window = [w for w in windows if w != ap2t_window][-1]
        driver.switch_to.window(webmail_window)
        wait.until(EC.url_contains("webmail.pln.co.id"))
        time.sleep(3)

        wb_username = wait.until(
            EC.presence_of_element_located((By.ID, "username"))
        )
        wb_username.clear()
        wb_username.send_keys(IAM_USERNAME)

        wb_password = driver.find_element(By.ID, "password")
        wb_password.clear()
        wb_password.send_keys(WEBMAIL_PASSWORD)

        try:
            masuk_webmail_btn = wait.until(
                EC.presence_of_element_located((
                    By.XPATH,
                    "//button[@id='submitButton'] | //input[@id='submitButton'] |"
                    " //button[@type='submit'] | //input[@type='submit']",
                ))
            )
            driver.execute_script("arguments[0].click();", masuk_webmail_btn)
        except Exception:
            wb_password.send_keys(Keys.RETURN)

        # Panggil handle_save_popup setelah klik login webmail
        for _ in range(3):
            handle_save_popup(driver)
            time.sleep(1)

        print("Menunggu inbox webmail tersinkronisasi (8 detik)...")
        time.sleep(8)

        try:
            iam_links = wait.until(EC.presence_of_all_elements_located((
                By.XPATH,
                "//*[contains(translate(text(), 'IAMPLN', 'iampln'), 'iam pln') or"
                " contains(translate(text(), 'IAMPLN', 'iampln'), 'iam')]",
            )))
            if iam_links:
                iam_links[0].click()
                print("Berhasil mengklik email IAM PLN terbaru.")
                time.sleep(4)
        except Exception:
            pass

        otp_code = None
        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text
            matches = re.findall(r"\b(\d{6})\b", page_text)
            if matches:
                otp_code = matches[-1]
        except Exception:
            pass

        driver.close()
        driver.switch_to.window(ap2t_window)
        time.sleep(2)

        # -------------------------------------------------------------
        # LANGKAH 4: PASTE OTP & TEKAN "VERIFIKASI"
        # -------------------------------------------------------------
        print(f"OTP yang diambil: {otp_code}")
        if otp_code:
            otp_input = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'input[formcontrolname="token"]')
                )
            )
            otp_input.click()
            otp_input.clear()
            otp_input.send_keys(otp_code)
            time.sleep(1)

            verifikasi_btn = wait.until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//button[contains(translate(text(), 'VERIFIKASI', 'verifikasi'),"
                    " 'verifikasi')] | //input[@type='submit' and"
                    " contains(translate(@value, 'VERIFIKASI', 'verifikasi'),"
                    " 'verifikasi')]",
                ))
            )
            verifikasi_btn.click()
            print("OTP berhasil diverifikasi pada IAM PLN.")

        time.sleep(4)

        # -------------------------------------------------------------
        # LANGKAH 5: SETELAH VERIFIKASI, JALANKAN Enkripsi_AP2T.exe
        # -------------------------------------------------------------
        exe_path = ENKRIPSI_EXE_PATH
        work_dir = os.path.dirname(exe_path) or LEGACY_BOT_DIR

        if Application is None or pyperclip is None:
            raise RuntimeError(
                "pywinauto dan pyperclip diperlukan untuk menjalankan Enkripsi_AP2T.exe (khusus Windows)."
            )

        p = subprocess.Popen([exe_path], cwd=work_dir)
        time.sleep(3)

        app = Application(backend="uia").connect(path=exe_path, timeout=5)
        win = app.top_window()
        win.child_window(
            title="Copy to Clipboard", control_type="Button"
        ).click()
        time.sleep(1)
        encrypted_text = pyperclip.paste()
        p.kill()
        print("Berhasil menyalin string enkripsi dari Enkripsi_AP2T.exe.")

        driver.switch_to.window(ap2t_window)
        time.sleep(1)

        try:
            input_field = wait.until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    'input[type="text"], input[type="encryption"], input',
                ))
            )
            input_field.click()
            input_field.clear()
            input_field.send_keys(encrypted_text)
        except Exception:
            driver.execute_script(
                f"arguments[0].value = '{encrypted_text}';", input_field
            )
        time.sleep(1)

        try:
            login_sso_btn2 = wait.until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//button[contains(translate(., 'LOGINSSO', 'loginss0'), 'login sso')"
                    " or contains(translate(., 'SSO', 'sso'), 'sso')]",
                ))
            )
            login_sso_btn2.click()
        except Exception:
            driver.execute_script("document.querySelector('button').click();")
        time.sleep(5)

        try:
            body_txt = driver.find_element(By.TAG_NAME, "body").text
            if "reset session" in body_txt.lower() or "sedang digunakan" in body_txt.lower():
                print("Mendeteksi konflik sesi, mengklik Reset Session...")
                for btn in driver.find_elements(By.CSS_SELECTOR, "button, a"):
                    if "reset" in btn.text.lower():
                        btn.click()
                        time.sleep(2)
                        break
                try:
                    input_field = wait.until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, 'input[type="text"], input[type="password"], input')
                        )
                    )
                    input_field.click()
                    input_field.clear()
                    input_field.send_keys(encrypted_text)
                except Exception:
                    driver.execute_script(
                        f"arguments[0].value = '{encrypted_text}';", input_field
                    )
                time.sleep(1)
                login_sso_btn2.click()
                time.sleep(3)
        except Exception as e:
            print("Reset session check err:", e)

        print("Berhasil login ke New AP2T!")
        driver.get("http://newap2t.pln.co.id/crm/")
        time.sleep(10)
        try:
            driver.execute_script("""
              fetch('http://newap2t.pln.co.id/rtr-laporan/rtr-laporan-terpusat/api/reports/laporan-tul-III-09/laporan', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({unitup: '32111', tahun: '2026', bulan: '1'})
              }).catch(e => {});
            """)
            time.sleep(5)
        except Exception:
            pass

        # -------------------------------------------------------------
        # LANGKAH 6: AMBIL USER-TOKEN & SIMPAN
        # -------------------------------------------------------------
        user_token = ""
        for _ in range(15):
            user_token = driver.execute_script("""
              try {
                  let acc = localStorage.getItem('account');
                  if (acc) {
                      let obj = JSON.parse(acc);
                      if (obj.token) return obj.token;
                  }
                  let ut = localStorage.getItem('user-token');
                  if (ut && ut.length > 50) return ut;

                  for (let i = 0; i < localStorage.length; i++) {
                      let key = localStorage.key(i);
                      let val = localStorage.getItem(key);
                      if (val && val.startsWith('eyJ') && val.length > 100) {
                          return val;
                      }
                  }
              } catch(e) {}
              return "";
            """)
            if user_token and len(user_token) > 50:
                break
            time.sleep(2)

        if user_token and len(user_token) > 20:
            cookies = driver.get_cookies()
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            token_info = {
                "user_token": user_token,
                "cookie": cookie_str,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_token_json(token_info)
            print("[UAT SUKSES] User token dan cookies berhasil diekstrak.")
        else:
            print("[WARNING] Token dari localStorage kosong, mencoba ambil dari performance logs...")
            for entry in driver.get_log("performance"):
                try:
                    msg = json.loads(entry["message"])["message"]
                    if msg.get("method") == "Network.requestWillBeSent":
                        headers = msg.get("params", {}).get("request", {}).get("headers", {})
                        auth = headers.get("Authorization", "")
                        if auth.startswith("Bearer eyJ") and len(auth) > 100:
                            user_token = auth
                            cookies = driver.get_cookies()
                            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                            token_info = {
                                "user_token": user_token,
                                "cookie": cookie_str,
                                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            }
                            save_token_json(token_info)
                            print(f"[UAT SUKSES] Token berhasil diambil dari network request: {user_token[:40]}...")
                            break
                except Exception:
                    pass

            if not user_token or len(user_token) < 50:
                print("[ERROR] Gagal mengambil token dari localStorage dan performance logs.")
                save_token_json({"user_token": "INVALID", "cookie": ""})
                sys.exit(1)

        time.sleep(2)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
