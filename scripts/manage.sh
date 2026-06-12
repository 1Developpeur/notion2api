#!/bin/bash
# Notion-AI service management script.

case "$1" in
    start)
        echo "Starting services..."
        docker compose up -d
        ;;
    stop)
        echo "Stopping services..."
        docker compose down
        ;;
    restart)
        echo "Restarting services..."
        docker compose restart
        ;;
    status)
        echo "Service status:"
        docker compose ps
        ;;
    logs)
        echo "Showing logs. Press Ctrl+C to exit."
        docker compose logs -f
        ;;
    build)
        echo "Rebuilding image..."
        docker compose build --no-cache
        ;;
    update)
        echo "Updating and restarting services..."
        git pull
        docker compose build
        docker compose up -d
        ;;
    clean)
        echo "Cleaning containers and images..."
        docker compose down -v
        docker system prune -f
        ;;
    backup)
        BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$BACKUP_DIR"
        cp -r data "$BACKUP_DIR/" 2>/dev/null || true
        echo "Backup complete: $BACKUP_DIR"
        ;;
    restore)
        if [ -z "$2" ]; then
            echo "Specify a backup directory, for example: ./manage.sh restore backups/20240306_120000"
            exit 1
        fi
        echo "Restoring database..."
        cp -r "$2/data" . 2>/dev/null || true
        echo "Restore complete. Restart services with: ./manage.sh restart"
        ;;
    shell)
        echo "Opening container shell..."
        docker compose exec notion-ai /bin/bash
        ;;
    test)
        echo "Testing API..."
        curl -s http://localhost:8000/health | python -m json.tool
        ;;
    *)
        echo "Notion-AI service management script"
        echo "Usage: ./manage.sh {command}"
        echo "Commands: start, stop, restart, status, logs, build, update, clean, backup, restore, shell, test"
        ;;
esac
