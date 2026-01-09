# Alembic Migration Guide

Alembic - SQLAlchemy uchun professional database migration tool.

## 📋 Alembic nima?

Alembic database schema o'zgarishlarini versiya qilish va boshqarish uchun ishlatiladi:
- ✅ Schema o'zgarishlarini versiya qilish
- ✅ Migration scriptlarini yaratish
- ✅ Database versiyasini boshqarish
- ✅ Rollback qilish imkoniyati
- ✅ Autogenerate - modellardan avtomatik migration yaratish

## 🚀 Ishlatish

### 1. Birinchi migration yaratish (initial schema)

```bash
# Alembic ni sozlash (faqat bir marta)
alembic init migrations/alembic

# Birinchi migration yaratish
alembic revision --autogenerate -m "Initial schema"

# Migration ni ishga tushirish
alembic upgrade head
```

### 2. Schema o'zgarishlarini migration qilish

```bash
# 1. Model faylini o'zgartiring (bot/models/schema.py)

# 2. Autogenerate orqali migration yaratish
alembic revision --autogenerate -m "Add new column to users table"

# 3. Migration faylini tekshiring (migrations/alembic/versions/)

# 4. Migration ni ishga tushirish
alembic upgrade head
```

### 3. Migration holatini ko'rish

```bash
# Joriy versiyani ko'rish
alembic current

# Barcha migrationlarni ko'rish
alembic history

# Keyingi migrationni ko'rish
alembic show head
```

### 4. Rollback qilish

```bash
# Bir versiya orqaga qaytish
alembic downgrade -1

# Muayyan versiyaga qaytish
alembic downgrade <revision_id>

# Barcha migrationlarni bekor qilish
alembic downgrade base
```

## 📝 Migration fayl struktura

Har bir migration fayli quyidagi strukturaga ega:

```python
"""Add new column

Revision ID: abc123
Revises: def456
Create Date: 2026-01-09 14:00:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'abc123'
down_revision = 'def456'
branch_labels = None
depends_on = None

def upgrade():
    # Migration qilish
    op.add_column('users', sa.Column('new_field', sa.String(255)))

def downgrade():
    # Rollback qilish
    op.drop_column('users', 'new_field')
```

## ⚠️ Muhim eslatmalar

1. **Migration fayllarini tekshiring**: Autogenerate har doim to'g'ri bo'lmaydi
2. **Backup yarating**: Production'da migration oldidan backup qiling
3. **Test qiling**: Avval test muhitida sinab ko'ring
4. **Data migration**: Agar ma'lumotlarni ko'chirish kerak bo'lsa, migration faylida qo'shing

## 🔄 Workflow

1. Model o'zgartirish (`bot/models/schema.py`)
2. Migration yaratish: `alembic revision --autogenerate -m "Description"`
3. Migration faylini tekshirish va tuzatish
4. Migration ishga tushirish: `alembic upgrade head`
5. Test qilish

## 📚 Qo'shimcha ma'lumot

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Migrations](https://docs.sqlalchemy.org/en/20/core/metadata.html)
