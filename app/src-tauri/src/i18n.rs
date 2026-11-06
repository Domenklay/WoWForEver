//! Player messages in Russian, French, English, Spanish and Portuguese (Latin America).
//! The UI sends the language it uses (`set_language`); English is the fallback.

use std::fmt::Display;
use std::sync::atomic::{AtomicUsize, Ordering};

static LANG: AtomicUsize = AtomicUsize::new(1);

/// fr, en, es, pt, ru (anything else: en).
pub fn set(lang: &str) {
    let i = match lang.get(..2).unwrap_or("").to_ascii_lowercase().as_str() {
        "fr" => 0,
        "es" => 2,
        "pt" => 3,
        "ru" => 4,
        _ => 1,
    };
    LANG.store(i, Ordering::Relaxed);
}

/// The message in the current language.
pub fn t(key: &str) -> &'static str {
    let texts = MESSAGES
        .iter()
        .find(|(k, _)| *k == key)
        .map(|(_, v)| v)
        .unwrap_or(&[""; 4]);
    let language = LANG.load(Ordering::Relaxed);
    if language == 4 {
        return RUSSIAN
            .iter()
            .find(|(k, _)| *k == key)
            .map(|(_, v)| *v)
            .unwrap_or(texts[1]);
    }
    texts[language]
}

/// The message with each `{}` replaced by the next argument.
pub fn tf(key: &str, args: &[&dyn Display]) -> String {
    let mut out = String::new();
    let mut args = args.iter();
    let mut parts = t(key).split("{}").peekable();
    while let Some(part) = parts.next() {
        out.push_str(part);
        if parts.peek().is_some() {
            if let Some(a) = args.next() {
                out.push_str(&a.to_string());
            }
        }
    }
    out
}

type Texts = [&'static str; 4];

#[rustfmt::skip]
const MESSAGES: &[(&str, Texts)] = &[
    ("addon_dev_mode", ["Développement des addons actif : les fichiers locaux sont conservés.", "AddOn development is enabled: local files are preserved.", "Desarrollo de addons activado: se conservan los archivos locales.", "Desenvolvimento de addons ativado: os arquivos locais são preservados."]),
    ("addon_dev_preserved", ["Dossier local {} conservé sans mise à jour.", "Keeping local folder {} without updating it.", "Se conserva la carpeta local {} sin actualizarla.", "Pasta local {} preservada sem atualização."]),
    ("addon_checking", ["Vérification des extensions de jeu…", "Checking game AddOns…", "Comprobando complementos del juego…", "Verificando addons do jogo…"]),
    ("addon_ready", ["Extension installée et vérifiée.", "AddOn is installed and verified.", "Complemento instalado y verificado.", "Addon instalado e verificado."]),
    ("addon_downloading", ["Téléchargement de Forever Ascension : {}", "Downloading Forever Ascension: {}", "Descargando Forever Ascension: {}", "Baixando Forever Ascension: {}"]),
    ("addon_backup", ["Ancien addon sauvegardé : {}", "Previous AddOn backed up: {}", "Copia del addon anterior: {}", "Backup do addon anterior: {}"]),
    ("addon_failed", ["Installation de l’extension impossible : {}", "Could not install game AddOn: {}", "No se pudo instalar el complemento: {}", "Não foi possível instalar o addon: {}"]),
    ("addon_link", ["Le chemin de l’addon contient un lien.", "The AddOn path contains a link or reparse point.", "La ruta del addon contiene un enlace.", "O caminho do addon contém um link."]),
    ("official_managed_incomplete", ["Le téléchargement géré est incomplet. Reprenez le téléchargement ou la réparation dans Téléchargement du jeu.", "This managed client is incomplete. Resume downloading or repair it in Game downloads.", "Este cliente administrado está incompleto. Continúa la descarga o repáralo en Descarga del juego.", "Este cliente gerenciado está incompleto. Continue o download ou repare em Download do jogo."]),
    ("official_ready", ["La version correspond au profil du serveur. Vous pouvez connecter ce client.", "The version matches the server profile. You can connect this client.", "La versión coincide con el perfil del servidor. Puedes conectar este cliente.", "A versão corresponde ao perfil do servidor. Você pode conectar este cliente."]),
    ("official_unknown_version", ["Impossible de lire FileVersion dans l’EXE. Terminez l’installation dans le launcher source.", "Could not read the EXE FileVersion. Finish installation in the source launcher.", "No se pudo leer FileVersion del EXE. Termina la instalación en el launcher de origen.", "Não foi possível ler FileVersion do EXE. Conclua a instalação no launcher de origem."]),
    ("official_unsupported", ["Cette branche n’est pas compatible avec un serveur Forever 1.60.1. Changer l’adresse ne convertit pas Retail ou Classic Era.", "This branch is not supported by a Forever 1.60.1 server. Changing the address does not convert Retail or Classic Era.", "Esta rama no es compatible con un servidor Forever 1.60.1. Cambiar la dirección no convierte Retail ni Classic Era.", "Esta versão não é compatível com um servidor Forever 1.60.1. Alterar o endereço não converte Retail ou Classic Era."]),
    ("official_missing_storage", ["Le stockage partagé Data/data est absent. Choisissez l’installation complète et terminez le téléchargement dans le launcher source.", "The shared Data/data storage is missing. Select the complete installation and finish downloading in the source launcher.", "Falta Data/data. Elige la instalación completa y termina la descarga en el launcher de origen.", "Data/data está ausente. Escolha a instalação completa e conclua o download no launcher de origem."]),
    ("official_mismatch", ["Client {}. Profil du serveur : 1.60.1.{}. Une version serveur compatible est nécessaire.", "Client {}. Server profile: 1.60.1.{}. A compatible server build is required to connect.", "Cliente {}. Perfil del servidor: 1.60.1.{}. Se necesita una compilación compatible del servidor.", "Cliente {}. Perfil do servidor: 1.60.1.{}. É necessária uma compilação compatível do servidor."]),
    ("official_no_exe", ["Choisissez le dossier du jeu installé ou la racine World of Warcraft.", "Choose the installed game folder or the World of Warcraft root.", "Elige la carpeta del juego instalado o la raíz de World of Warcraft.", "Escolha a pasta do jogo instalado ou a raiz de World of Warcraft."]),
    ("official_protected", ["Protection des fichiers active : téléchargements, réparations et paquets expérimentaux Multi désactivés.", "File protection is enabled. Multi downloads, recovery and experimental packages are disabled.", "La protección está activada. Las descargas, restauraciones y paquetes experimentales de Multi están desactivados.", "A proteção está ativa. Downloads, recuperação e pacotes experimentais do Multi estão desativados."]),
    ("bad_server_address", ["Adresse ou ports du serveur invalides.", "Invalid server address or ports.", "Dirección o puertos del servidor no válidos.", "Endereço ou portas do servidor inválidos."]),
    ("ca_invalid", ["Choisissez un certificat CA public PEM valide, jamais une clé privée.", "Choose a valid public PEM CA certificate, never a private key.", "Elige un certificado CA público PEM válido, nunca una clave privada.", "Escolha um certificado CA público PEM válido, nunca uma chave privada."]),
    ("ca_missing", ["Choisissez le certificat CA public dans les paramètres du serveur.", "Choose the public server CA certificate in Server settings.", "Elige el certificado CA público en los ajustes del servidor.", "Escolha o certificado CA público nas configurações do servidor."]),
    ("ca_read", ["Lecture du certificat CA : {}", "Reading the public CA certificate: {}", "Leyendo el certificado CA público: {}", "Lendo o certificado CA público: {}"]),
    ("pkg_unready", ["Ce paquet n’est pas prêt pour l’installation.", "This package is not ready for installation.", "Este paquete aún no está listo para instalar.", "Este pacote ainda não está pronto para instalar."]),
    ("pkg_client", ["Le paquet ne correspond pas au client choisi.", "The package does not match the selected client.", "El paquete no coincide con el cliente seleccionado.", "O pacote não corresponde ao cliente selecionado."]),
    ("pkg_changed", ["Les fichiers du client ont changé. Le paquet ou la restauration doit être préparé à nouveau.", "Client files have changed. The package or rollback needs to be prepared again.", "Los archivos del cliente cambiaron. Hay que preparar de nuevo el paquete o la restauración.", "Os arquivos do cliente mudaram. É necessário preparar novamente o pacote ou a restauração."]),
    ("pkg_busy", ["Une opération ou le jeu est déjà en cours.", "A package operation or the game is already running.", "Ya hay una operación o el juego en ejecución.", "Já existe uma operação ou o jogo em execução."]),
    ("pkg_recovery", ["Restaurez d’abord le paquet interrompu.", "Roll back the interrupted package first.", "Primero restaura el paquete interrumpido.", "Restaure primeiro o pacote interrompido."]),
    ("pkg_empty", ["Aucun paquet à restaurer.", "No installed package to roll back.", "No hay ningún paquete que restaurar.", "Não há pacote instalado para restaurar."]),
    ("pkg_io", ["Impossible de lire ou écrire les fichiers du paquet.", "Could not read or write package files.", "No se pudieron leer o escribir los archivos del paquete.", "Não foi possível ler ou gravar os arquivos do pacote."]),
    ("pkg_invalid", ["Paquet invalide ou fichiers non conformes.", "Invalid package or file integrity check failed.", "Paquete inválido o verificación de archivos fallida.", "Pacote inválido ou falha na verificação dos arquivos."]),
    ("pkg_close_game", ["Fermez toutes les copies du jeu avant de modifier un paquet.", "Close all game clients before changing a package.", "Cierra todos los clientes del juego antes de cambiar un paquete.", "Feche todos os clientes do jogo antes de alterar um pacote."]),
    ("pkg_platform", ["L’installation de paquets est actuellement disponible sur Windows et Linux.", "Package installation is currently available on Windows and Linux.", "La instalación de paquetes está disponible actualmente en Windows y Linux.", "A instalação de pacotes está disponível atualmente no Windows e Linux."]),
    // launch steps
    ("step_connecting", ["Connexion au serveur…", "Connecting to the server…", "Conectando con el servidor…", "Conectando ao servidor…"]),
    ("step_preparing", ["Préparation du jeu…", "Preparing the game…", "Preparando el juego…", "Preparando o jogo…"]),
    ("step_launching", ["Lancement de World of Warcraft…", "Starting World of Warcraft…", "Iniciando World of Warcraft…", "Iniciando World of Warcraft…"]),
    ("running", ["Processus du jeu détecté : préparation de la connexion…", "Game process found: preparing the connection…", "Proceso del juego encontrado: preparando la conexión…", "Processo do jogo encontrado: preparando a conexão…"]),
    ("ready", ["Clé du serveur prête : vous pouvez vous connecter au jeu.", "Server key ready: you can sign in to the game.", "Clave del servidor lista: puedes iniciar sesión en el juego.", "Chave do servidor pronta: você pode entrar no jogo."]),
    ("closed", ["Le jeu est fermé", "The game is closed", "El juego se cerró", "O jogo foi fechado"]),
    ("not_started", ["Jeu introuvable après 3 minutes dans le dossier choisi.", "No game process from the selected folder found within 3 minutes.", "No se encontró el proceso del juego de la carpeta elegida en 3 minutos.", "Nenhum processo do jogo da pasta escolhida foi encontrado em 3 minutos."]),
    ("mac_copying", ["Copie du jeu pour Forever (première fois ou après une mise à jour)…", "Copying the game for Forever (first time or after an update)…", "Copiando el juego para Forever (primera vez o tras una actualización)…", "Copiando o jogo para o Forever (primeira vez ou após uma atualização)…"]),
    ("mac_signing", ["Signature de la copie du jeu…", "Signing the game copy…", "Firmando la copia del juego…", "Assinando a cópia do jogo…"]),
    // launch errors
    ("already_running", ["le jeu est déjà lancé", "the game is already running", "el juego ya está abierto", "o jogo já está aberto"]),
    ("game_not_found", ["Jeu introuvable : choisissez _forever_ (Wow.exe), _classic_beta_ (WowB.exe) ou la racine.", "Game not found: choose _forever_ (Wow.exe), _classic_beta_ (WowB.exe), or the installation root.", "Juego no encontrado: elige _forever_ (Wow.exe), _classic_beta_ (WowB.exe) o la raíz.", "Jogo não encontrado: escolha _forever_ (Wow.exe), _classic_beta_ (WowB.exe) ou a raiz."]),
    ("login_first", ["connectez-vous d'abord", "log in first", "inicia sesión primero", "entre na sua conta primeiro"]),
    ("session_expired", ["session expirée : reconnectez-vous", "session expired: log in again", "sesión caducada: vuelve a iniciar sesión", "sessão expirada: entre novamente"]),
    ("session_save", ["enregistrement de la session : {}", "saving the session: {}", "guardando la sesión: {}", "salvando a sessão: {}"]),
    ("launch_failed", ["lancement de {} : {}", "starting {}: {}", "iniciando {}: {}", "iniciando {}: {}"]),
    ("wtf_folder", ["dossier WTF : {}", "WTF folder: {}", "carpeta WTF: {}", "pasta WTF: {}"]),
    ("registry", ["registre : {}", "registry: {}", "registro: {}", "registro: {}"]),
    ("mac_failed", ["{} a échoué : {}", "{} failed: {}", "{} falló: {}", "{} falhou: {}"]),
    ("mac_not_started", ["le jeu n'a pas pu démarrer (open : {})", "the game could not start (open: {})", "el juego no pudo arrancar (open: {})", "o jogo não pôde iniciar (open: {})"]),
    ("mac_module", ["le module Forever ne s'est pas chargé dans le jeu", "the Forever module was not loaded into the game", "el módulo Forever no se cargó en el juego", "o módulo Forever não foi carregado no jogo"]),
    ("mac_key", ["dérivation de la clé du ticket impossible", "could not derive the ticket key", "no se pudo derivar la clave del ticket", "não foi possível derivar a chave do ticket"]),
    ("mac_encrypt", ["chiffrement du ticket impossible ({})", "could not encrypt the ticket ({})", "no se pudo cifrar el ticket ({})", "não foi possível criptografar o ticket ({})"]),
    ("mac_user", ["nom d'utilisateur inconnu", "unknown user name", "nombre de usuario desconocido", "nome de usuário desconhecido"]),
    // server API
    ("address_not_found", ["adresse du serveur introuvable ({})", "server address not found ({})", "dirección del servidor no encontrada ({})", "endereço do servidor não encontrado ({})"]),
    ("unexpected_answer", ["réponse inattendue du serveur", "unexpected answer from the server", "respuesta inesperada del servidor", "resposta inesperada do servidor"]),
    ("authenticator", ["ce compte utilise un authentificateur, non géré par le launcher", "this account uses an authenticator, which the launcher does not support", "esta cuenta usa un autenticador, que el launcher no admite", "esta conta usa um autenticador, que o launcher não suporta"]),
    ("bad_login", ["e-mail ou mot de passe incorrect", "wrong e-mail or password", "correo o contraseña incorrectos", "e-mail ou senha incorretos"]),
    ("remember_refused", ["le serveur refuse la connexion automatique (HTTP {})", "the server refuses automatic login (HTTP {})", "el servidor rechaza el inicio de sesión automático (HTTP {})", "o servidor recusa o login automático (HTTP {})"]),
    ("banned", ["compte banni", "account banned", "cuenta suspendida", "conta banida"]),
    ("server_error", ["erreur du serveur (HTTP {})", "server error (HTTP {})", "error del servidor (HTTP {})", "erro do servidor (HTTP {})"]),
    ("unreachable", ["serveur injoignable", "server unreachable", "servidor inaccesible", "servidor inacessível"]),
    ("network_error", ["erreur réseau : {}", "network error: {}", "error de red: {}", "erro de rede: {}"]),
    ("no_news", ["pas de nouveautés (HTTP {})", "no news (HTTP {})", "sin novedades (HTTP {})", "sem novidades (HTTP {})"]),
    ("unexpected_site", ["réponse inattendue du site", "unexpected answer from the website", "respuesta inesperada del sitio", "resposta inesperada do site"]),
    // PC checks and setup
    ("wine_system", ["Wine (système)", "Wine (system)", "Wine (sistema)", "Wine (sistema)"]),
    ("no_resolve", ["{} ne se résout pas", "{} does not resolve", "{} no se resuelve", "{} não é resolvido"]),
    ("hosts_wrong", ["{} → {} (attendu {})", "{} → {} (expected {})", "{} → {} (se esperaba {})", "{} → {} (esperado {})"]),
    ("hosts_missing", ["{} n'est pas dans le fichier hosts", "{} is not in the hosts file", "{} no está en el archivo hosts", "{} não está no arquivo hosts"]),
    ("cert_store_unreadable", ["magasin de certificats illisible", "certificate store unreadable", "almacén de certificados ilegible", "repositório de certificados ilegível"]),
    ("cert_ok_windows", ["certificat du serveur reconnu par Windows", "server certificate trusted by Windows", "certificado del servidor reconocido por Windows", "certificado do servidor reconhecido pelo Windows"]),
    ("cert_missing", ["certificat du serveur non installé", "server certificate not installed", "certificado del servidor no instalado", "certificado do servidor não instalado"]),
    ("cert_ok_macos", ["certificat du serveur approuvé par macOS", "server certificate trusted by macOS", "certificado del servidor aprobado por macOS", "certificado do servidor aprovado pelo macOS"]),
    ("cert_not_trusted", ["certificat du serveur non approuvé", "server certificate not trusted", "certificado del servidor no aprobado", "certificado do servidor não aprovado"]),
    ("cert_ok_prefix", ["certificat installé dans le préfixe Wine", "certificate installed in the Wine prefix", "certificado instalado en el prefijo de Wine", "certificado instalado no prefixo do Wine"]),
    ("prefix_missing", ["préfixe Wine pas encore créé", "Wine prefix not created yet", "prefijo de Wine aún no creado", "prefixo do Wine ainda não criado"]),
    ("cert_not_in_prefix", ["certificat absent du préfixe Wine", "certificate missing from the Wine prefix", "certificado ausente del prefijo de Wine", "certificado ausente do prefixo do Wine"]),
    ("bad_portal", ["Le portail doit être un nom DNS de certificat, sans IP ni port.", "Portal must be a certificate DNS hostname, without an IP or port.", "El portal debe ser un nombre DNS del certificado, sin IP ni puerto.", "O portal deve ser o nome DNS do certificado, sem IP nem porta."]),
    ("admin_refused", ["autorisation administrateur refusée", "administrator permission refused", "permiso de administrador denegado", "permissão de administrador recusada"]),
    ("install_wait", ["attente de l'installation impossible", "could not wait for the installation", "no se pudo esperar a la instalación", "não foi possível aguardar a instalação"]),
    ("install_failed", ["échec de l'installation (code {})", "installation failed (code {})", "la instalación falló (código {})", "a instalação falhou (código {})"]),
    ("hosts_prompt", ["Forever Launcher : ajout du serveur dans le fichier hosts.", "Forever Launcher: adding the server to the hosts file.", "Forever Launcher: añadiendo el servidor al archivo hosts.", "Forever Launcher: adicionando o servidor ao arquivo hosts."]),
    ("hosts_refused", ["autorisation refusée pour le fichier hosts", "permission refused for the hosts file", "permiso denegado para el archivo hosts", "permissão recusada para o arquivo hosts"]),
    ("hosts_write_failed", ["écriture du fichier hosts impossible : {}", "could not write the hosts file: {}", "no se pudo escribir el archivo hosts: {}", "não foi possível gravar o arquivo hosts: {}"]),
    ("hosts_write_failed_pkexec", ["écriture du fichier hosts impossible (pkexec)", "could not write the hosts file (pkexec)", "no se pudo escribir el archivo hosts (pkexec)", "não foi possível gravar o arquivo hosts (pkexec)"]),
    ("cert_trust_failed", ["certificat non approuvé : {}", "certificate not trusted: {}", "certificado no aprobado: {}", "certificado não aprovado: {}"]),
    ("prefix_error", ["préfixe {} : {}", "prefix {}: {}", "prefijo {}: {}", "prefixo {}: {}"]),
    ("wine_not_found", ["wine est introuvable", "wine not found", "no se encontró wine", "wine não encontrado"]),
    ("umu_not_found", ["umu-run est introuvable (paquet umu-launcher)", "umu-run not found (umu-launcher package)", "no se encontró umu-run (paquete umu-launcher)", "umu-run não encontrado (pacote umu-launcher)"]),
    ("proton_not_found", ["Proton introuvable : {}", "Proton not found: {}", "Proton no encontrado: {}", "Proton não encontrado: {}"]),
    ("command_failed", ["{} a échoué : {}", "{} failed: {}", "{} falló: {}", "{} falhou: {}"]),
    // key patcher (journal)
    ("bad_public_key", ["clé publique du serveur invalide", "invalid server public key", "clave pública del servidor no válida", "chave pública do servidor inválida"]),
    ("bad_region_group", ["groupe de région invalide (2-12, sauf 9)", "invalid region group (2-12, except 9)", "grupo de región no válido (2-12, excepto 9)", "grupo de região inválido (2-12, exceto 9)"]),
    ("write_refused", ["écriture refusée", "write refused", "escritura rechazada", "gravação recusada"]),
    ("verify_failed", ["vérification échouée", "check failed", "verificación fallida", "verificação falhou"]),
    ("memory_changed", ["la mémoire a changé pendant l'écriture", "memory changed while writing", "la memoria cambió durante la escritura", "a memória mudou durante a gravação"]),
    ("key_restored", ["clé du serveur remise en place", "server key put back", "clave del servidor restablecida", "chave do servidor restaurada"]),
    ("key_write_error", ["écriture de la clé : {}", "writing the key: {}", "escribiendo la clave: {}", "gravando a chave: {}"]),
    ("key_store_freed", ["magasin de clés libéré, nouvelle recherche à la prochaine connexion", "key store freed, searching again at the next login", "almacén de claves liberado, nueva búsqueda en el próximo inicio de sesión", "repositório de chaves liberado, nova busca no próximo login"]),
    ("game_process", ["processus du jeu : PID {}", "game process: PID {}", "proceso del juego: PID {}", "processo do jogo: PID {}"]),
    ("key_written", ["clé du serveur écrite (groupe {})", "server key written (group {})", "clave del servidor escrita (grupo {})", "chave do servidor gravada (grupo {})"]),
    ("key_write_retry", ["écriture de la clé : {}, nouvel essai", "writing the key: {}, retrying", "escribiendo la clave: {}, reintentando", "gravando a chave: {}, tentando de novo"]),
    ("waiting_realm", ["en attente de l'entrée dans le royaume…", "waiting for the realm login…", "esperando la entrada al reino…", "aguardando a entrada no reino…"]),
    ("many_key_stores", ["{} magasins de clés à la fois : attente", "{} key stores at once: waiting", "{} almacenes de claves a la vez: esperando", "{} repositórios de chaves ao mesmo tempo: aguardando"]),
    ("launch_executable", ["Exécutable du jeu : {}", "Game executable: {}", "Ejecutable del juego: {}", "Executável do jogo: {}"]),
    ("client_exit", ["Processus du jeu PID {} terminé ; code {}", "Game process PID {} ended; exit code {}", "El proceso del juego PID {} terminó; código {}", "O processo do jogo PID {} encerrou; código {}"]),
    ("exit_unknown", ["inconnu", "unknown", "desconocido", "desconhecido"]),
    ("closed_before_ready", ["Le client s’est fermé avant la préparation de la clé serveur. Consultez ses journaux pour en connaître la raison.", "The client exited before its server key was ready. Its game logs are needed to determine why.", "El cliente se cerró antes de preparar la clave. Sus registros son necesarios para conocer la causa.", "O cliente fechou antes de preparar a chave. Os logs do jogo são necessários para identificar a causa."]),
];

#[rustfmt::skip]
const RUSSIAN: &[(&str,&str)] = &[
    ("addon_dev_mode", "Режим разработки аддонов включён: локальные файлы сохраняются."),
    ("addon_dev_preserved", "Оставляем локальную папку {} без обновления."),
    ("addon_checking", "Проверяем игровые дополнения…"),
    ("addon_ready", "Дополнение установлено и проверено."),
    ("addon_downloading", "Скачиваем Forever Ascension: {}"),
    ("addon_backup", "Резервная копия прежнего аддона: {}"),
    ("addon_failed", "Не удалось установить игровое дополнение: {}"),
    ("addon_link", "Папка аддона содержит ссылку или точку перенаправления."),
    ("official_managed_incomplete", "Загрузка управляемого клиента не завершена. Продолжите скачивание или восстановление в разделе «Загрузка игры»."),
    ("official_ready", "Версия совпадает с профилем сервера. Можно подключать клиент."),
    ("official_unknown_version", "Не удалось прочитать FileVersion EXE. Завершите установку в исходном лаунчере."),
    ("official_unsupported", "Эта ветка не поддерживается сервером Forever 1.60.1. Смена адреса не конвертирует Retail или Classic Era."),
    ("official_missing_storage", "Не найдено общее хранилище Data/data. Выберите установку целиком и завершите загрузку в исходном лаунчере."),
    ("official_mismatch", "Клиент {}. Профиль сервера: 1.60.1.{}. Для подключения требуется совместимая сборка сервера."),
    ("official_no_exe", "Выберите папку установленного клиента или корень World of Warcraft."),
    ("official_protected", "Защита файлов включена. Скачивание, восстановление и экспериментальные пакеты Multi отключены."),
    ("bad_server_address", "Некорректный адрес или порты сервера."),
    ("ca_invalid", "Выберите публичный CA-сертификат PEM, а не приватный ключ."),
    ("ca_missing", "Выберите публичный CA-сертификат в параметрах сервера."),
    ("ca_read", "Чтение публичного сертификата: {}"),
    ("pkg_unready", "Пакет не готов к установке."),
    ("pkg_client", "Пакет не соответствует выбранному клиенту."),
    ("pkg_changed", "Файлы клиента изменились. Пакет или откат нужно подготовить заново."),
    ("pkg_busy", "Игра или другая операция уже выполняется."),
    ("pkg_recovery", "Сначала откатите прерванную установку пакета."),
    ("pkg_empty", "Установленного пакета для отката нет."),
    ("pkg_io", "Не удалось прочитать или записать файлы пакета."),
    ("pkg_invalid", "Пакет некорректен или не прошёл проверку хешей."),
    ("pkg_close_game", "Закройте все копии игры перед изменением пакета."),
    ("pkg_platform", "Установка пакетов доступна на Windows и Linux."),
    ("step_connecting", "Подключаемся к серверу…"),
    ("step_preparing", "Подготавливаем игру…"),
    ("step_launching", "Запускаем World of Warcraft…"),
    ("running", "Процесс игры найден; подготавливаем подключение…"),
    ("ready", "Ключ сервера готов — можно входить в игру."),
    ("closed", "Игра закрыта"),
    ("not_started", "За три минуты не найден процесс игры из выбранной папки."),
    ("mac_copying", "Создаём копию клиента Forever — первый запуск или обновление…"),
    ("mac_signing", "Подписываем копию клиента…"),
    ("already_running", "игра уже запущена"),
    ("game_not_found", "Клиент не найден: выберите _forever_ (Wow.exe), _classic_beta_ (WowB.exe) или корень установки."),
    ("login_first", "сначала войдите в аккаунт"),
    ("session_expired", "сессия истекла — войдите заново"),
    ("session_save", "сохранение сессии: {}"),
    ("launch_failed", "запуск {}: {}"),
    ("wtf_folder", "папка WTF: {}"),
    ("registry", "реестр: {}"),
    ("mac_failed", "ошибка {}: {}"),
    ("mac_not_started", "не удалось запустить игру (open: {})"),
    ("mac_module", "модуль Forever не загрузился в игру"),
    ("mac_key", "не удалось получить ключ билета"),
    ("mac_encrypt", "не удалось зашифровать билет ({})"),
    ("mac_user", "неизвестное имя пользователя"),
    ("address_not_found", "не найден адрес сервера ({})"),
    ("unexpected_answer", "неожиданный ответ сервера"),
    ("authenticator", "аккаунт использует аутентификатор, который пока не поддерживается лаунчером"),
    ("bad_login", "неверная почта или пароль"),
    ("remember_refused", "сервер отказал в автоматическом входе (HTTP {})"),
    ("banned", "аккаунт заблокирован"),
    ("server_error", "ошибка сервера (HTTP {})"),
    ("unreachable", "сервер недоступен"),
    ("network_error", "ошибка сети: {}"),
    ("no_news", "новостей нет (HTTP {})"),
    ("unexpected_site", "неожиданный ответ сайта"),
    ("wine_system", "Системный Wine"),
    ("no_resolve", "не удалось определить адрес {}"),
    ("hosts_wrong", "{} → {} (ожидается {})"),
    ("hosts_missing", "{} отсутствует в файле hosts"),
    ("cert_store_unreadable", "не удалось прочитать хранилище сертификатов"),
    ("cert_ok_windows", "Windows доверяет сертификату сервера"),
    ("cert_missing", "сертификат сервера не установлен"),
    ("cert_ok_macos", "macOS доверяет сертификату сервера"),
    ("cert_not_trusted", "сертификат сервера не является доверенным"),
    ("cert_ok_prefix", "сертификат установлен в префиксе Wine"),
    ("prefix_missing", "префикс Wine ещё не создан"),
    ("cert_not_in_prefix", "сертификата нет в префиксе Wine"),
    ("bad_portal", "Укажите DNS-имя сертификата без IP и номера порта."),
    ("admin_refused", "доступ администратора не предоставлен"),
    ("install_wait", "не удалось дождаться завершения установки"),
    ("install_failed", "установка завершилась с ошибкой (код {})"),
    ("hosts_prompt", "Forever Multi: добавляем адрес сервера в файл hosts."),
    ("hosts_refused", "нет доступа к изменению файла hosts"),
    ("hosts_write_failed", "не удалось записать файл hosts: {}"),
    ("hosts_write_failed_pkexec", "не удалось записать файл hosts через pkexec"),
    ("cert_trust_failed", "не удалось установить доверие к сертификату: {}"),
    ("prefix_error", "префикс {}: {}"),
    ("wine_not_found", "Wine не найден"),
    ("umu_not_found", "umu-run не найден — требуется пакет umu-launcher"),
    ("proton_not_found", "Proton не найден: {}"),
    ("command_failed", "ошибка {}: {}"),
    ("bad_public_key", "некорректный публичный ключ сервера"),
    ("bad_region_group", "некорректная группа региона — допустимы 2–12, кроме 9"),
    ("write_refused", "запись запрещена"),
    ("verify_failed", "проверка не пройдена"),
    ("memory_changed", "память изменилась во время записи"),
    ("key_restored", "ключ сервера восстановлен"),
    ("key_write_error", "запись ключа: {}"),
    ("key_store_freed", "хранилище ключей освобождено — повторный поиск при подключении"),
    ("game_process", "процесс игры: PID {}"),
    ("key_written", "ключ сервера записан — группа {}"),
    ("key_write_retry", "запись ключа: {}; повторяем"),
    ("waiting_realm", "ожидаем подготовку подключения к игровому миру…"),
    ("many_key_stores", "одновременно найдено хранилищ ключей: {}; ожидаем"),
    ("launch_executable", "Исполняемый файл игры: {}"),
    ("client_exit", "Процесс игры PID {} завершился; код выхода {}"),
    ("exit_unknown", "неизвестен"),
    ("closed_before_ready", "Клиент завершился до готовности ключа сервера. Причину закрытия нужно искать в журналах игры."),
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_message_has_five_translations_with_the_same_placeholders() {
        for (key, texts) in MESSAGES {
            let n = texts[0].matches("{}").count();
            let russian = RUSSIAN.iter().find(|(k, _)| k == key).expect(key).1;
            assert!(!russian.is_empty());
            assert_eq!(russian.matches("{}").count(), n, "{key}: {russian}");
            for text in texts {
                assert!(!text.is_empty(), "{key}");
                assert_eq!(text.matches("{}").count(), n, "{key}: {text}");
            }
        }
    }

    #[test]
    fn formats_in_the_chosen_language() {
        set("es-419");
        assert_eq!(tf("server_error", &[&503]), "error del servidor (HTTP 503)");
        set("pt-BR");
        assert_eq!(t("banned"), "conta banida");
        set("ru-RU");
        assert_eq!(t("banned"), "аккаунт заблокирован");
        assert_eq!(tf("server_error", &[&503]), "ошибка сервера (HTTP 503)");
        set("de");
        assert_eq!(t("banned"), "account banned");
        set("fr");
    }
}
