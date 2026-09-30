# Maintainer: EXSCIO Core Team <info@exscio.local>
# Contributor: Arch Linux AI SIG
pkgname=exscio
pkgver=2.0.0
pkgrel=1
pkgdesc="Autonomous Enterprise Offline RAG System with Local LLM & WebKit2GTK GUI"
arch=('x86_64')
url="https://github.com/exscio/exscio"
license=('Proprietary')
depends=(
    'python>=3.10'
    'python-pip'
    'python-virtualenv'
    'webkit2gtk-4.1'
    'gtk3'
    'python-gobject'
    'openssl'
    'lsof'
    'xdg-utils'
)
optdepends=(
    'ollama: Native Arch Linux LLM inference daemon'
    'docker: Containerized LLM runtime and Open WebUI stack'
    'docker-compose: Multi-container deployment for local models'
    'cuda: NVIDIA GPU acceleration for PyTorch and Ollama'
    'nvidia-utils: GPU monitoring and hardware telemetry'
    'rocm-hip-sdk: AMD ROCm GPU compute platform'
    'rocm-smi-lib: AMD ROCm hardware monitoring'
)
install=exscio.install
source=()
sha256sums=()

package() {
    # 1. Корневая директория приложения
    install -d "$pkgdir/opt/exscio"

    # Безопасное копирование файлов проекта без рекурсивного захвата сборочных каталогов
    for item in "$startdir"/*; do
        bname="$(basename "$item")"
        case "$bname" in
            pkg|src|venv|__pycache__|*.pkg.tar.*|.git)
                continue
                ;;
            *)
                cp -a "$item" "$pkgdir/opt/exscio/"
                ;;
        esac
    done

    # Гарантируем права на выполнение shell-скриптов
    chmod 755 "$pkgdir/opt/exscio"/*.sh


    # 2. Исполняемые скрипты-обертки в /usr/bin
    install -d "$pkgdir/usr/bin"

    cat > "$pkgdir/usr/bin/exscio" <<'EOF'
#!/bin/sh
cd /opt/exscio && exec ./start.sh "$@"
EOF
    chmod 755 "$pkgdir/usr/bin/exscio"

    cat > "$pkgdir/usr/bin/exscio-api" <<'EOF'
#!/bin/sh
cd /opt/exscio && exec ./start_api.sh "$@"
EOF
    chmod 755 "$pkgdir/usr/bin/exscio-api"

    cat > "$pkgdir/usr/bin/exscio-switch" <<'EOF'
#!/bin/sh
cd /opt/exscio && exec ./switch_backend.sh "$@"
EOF
    chmod 755 "$pkgdir/usr/bin/exscio-switch"

    # 3. Интеграция в системное меню FreeDesktop
    install -Dm644 "$pkgdir/opt/exscio/exscio.desktop" "$pkgdir/usr/share/applications/exscio.desktop"
    
    # 4. Иконка приложения High-DPI
    if [ -f "$pkgdir/opt/exscio/static/exscio.png" ]; then
        install -Dm644 "$pkgdir/opt/exscio/static/exscio.png" "$pkgdir/usr/share/icons/hicolor/256x256/apps/exscio.png"
    elif [ -f "$pkgdir/opt/exscio/rag_icon.png" ]; then
        install -Dm644 "$pkgdir/opt/exscio/rag_icon.png" "$pkgdir/usr/share/icons/hicolor/256x256/apps/exscio.png"
    fi

    # 5. Systemd пользовательские службы
    install -Dm644 "$pkgdir/opt/exscio/exscio.service" "$pkgdir/usr/lib/systemd/user/exscio.service"
    install -Dm644 "$pkgdir/opt/exscio/exscio-api.service" "$pkgdir/usr/lib/systemd/user/exscio-api.service"
}
