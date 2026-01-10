# Inline Query (@bot_username) Sozlash

## Muammo
`@` yozganda botingiz taklif qilmayapti va quiz boshlanmayapti. Boshqa botlar chiqyapti, lekin sizniki chiqmayapti.

## Yechim

### ⚠️ MUHIM: Inline Query BotFather'da Yoqilishi Kerak!

Bu kod bilan hal qilib bo'lmaydi - bu Telegram API'ning talabidir. BotFather'da inline mode'ni yoqish **shart**.

### 1. BotFather'da Inline Mode'ni Yoqing (SHART!)

1. **BotFather'ni oching**: `@BotFather` ga kirib `/setinline` yuboring
2. **Botingizni tanlang**: Ro'yxatdan botingizni tanlang
3. **Inline placeholder yozing**: Masalan: `Quiz qidirish yoki quiz ID kiriting...`
4. **Inline feedback'ni yoqing**: "Yes" yuboring (statistika uchun)

**To'liq qadamlar:**
```
1. @BotFather ga kirish
2. /setinline yuborish
3. Botingizni tanlash (masalan: Quiz Bot)
4. Inline placeholder: "Quiz qidirish yoki quiz ID kiriting..."
5. Inline feedback: Yes
```

**Keyin bot @ yozilganda taklif qilishi kerak!**

### 2. Bot Description Sozlash

BotFather'da:
```
/setdescription
[Botingizni tanlang]
Quizlar yaratish va o'tkazish uchun bot. @bot_username yozib quizlarni qidiring.
```

### 3. Bot Short Description

```
/setabouttext
[Botingizni tanlang]
📝 Quizlarni qidirish va boshlash
```

### 4. Test Qilish

1. Botni qayta ishga tushiring (qayta tushurilgan)
2. Har qanday chatda `@bot_username` yozing
3. Bot takliflarida ko'rinishi kerak
4. Quizlarni tanlang va chatga yuboring
5. "🚀 Quizni boshlash" tugmasini bosing

## Kodda Qilingan O'zgarishlar

✅ `InlineQueryHandler` ro'yxatdan o'tkazilgan
✅ `ChosenInlineResultHandler` qo'shilgan  
✅ Bot description va short description sozlandi
✅ Logging yaxshilandi
✅ Quiz boshlash xatolari tuzatildi (`reply_markup` muammosi)

## Tekshirish

Agar inline query hali ham ishlamasa:

1. BotFather'da inline mode yoqilganligini tekshiring
2. Bot loglarini tekshiring: `journalctl -u quiz-bot.service -f`
3. `@bot_username test` yozib inline query yuborishga harakat qiling
4. Loglarda `📥 Inline query received` ko'rinishi kerak

## Qo'shimcha Ma'lumot

- Inline query Telegram API orqali BotFather sozlamalari bilan boshqariladi
- Bot kodida barcha kerakli handlerlar mavjud
- Bot description va short description avtomatik sozlanadi (bot ishga tushganda)
