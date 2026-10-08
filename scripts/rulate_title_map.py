import csv, re, time, unicodedata
from difflib import SequenceMatcher
from urllib.parse import quote_plus, urljoin
import requests
from bs4 import BeautifulSoup

BOOKS = [
  {
    "en": "Global Lord: 100% Drop Rate",
    "ru": "Глобальный Лорд: 100% шанс выпадения"
  },
  {
    "en": "They asked me to open a workshop, and you started a mech war?",
    "ru": "Просили открыть мастерскую, а ты развязал войну мехов?"
  },
  {
    "en": "Parallel World: Awakened the Hogyoku at the beginning",
    "ru": "Параллельный мир: Пробудил Хогьёку в начале"
  },
  {
    "en": "I Secretly Develop Myself In The Demon World",
    "ru": "Мир демонов: Моё тайное развитие"
  },
  {
    "en": "Marvel has a tavern",
    "ru": "Марвел: Есть одна таверна..."
  },
  {
    "en": "Wizard: Leveling up through the Skill Tree",
    "ru": "Чародей: Прокачка через древо навыков"
  },
  {
    "en": "I'm Just Investing! Why Do You Say I Raise Dead Soldiers?",
    "ru": "Я просто инвестирую! С чего вы взяли, что я воспитываю смертников?"
  },
  {
    "en": "You're an assassin! Why the hell is everything pumped into ranged combat?",
    "ru": "Ты же ассасин! Какого чёрта всё вкачано в дальний бой?"
  },
  {
    "en": "Lord of the People: Discount Artifact For Signing In at the Start",
    "ru": "Лорд человечества: Ежедневные скидки за вход в систему"
  },
  {
    "en": "Did the student want my Double pupils? In return, I will rip out her Divine Bone!",
    "ru": "Ученица захотела мои Двойные зрачки? В ответ я вырву её Божественную Кость!"
  },
  {
    "en": "Horror: A Comics Character Every Week",
    "ru": "Ужасы: Новый аниме-персонаж каждую неделю"
  },
  {
    "en": "Marvel: The Unlicensed Healer",
    "ru": "Марвел: Неспешная жизнь одного отца"
  },
  {
    "en": "Marvel: The man behind the scenes",
    "ru": "Марвел: Человек за кулисами"
  },
  {
    "en": "Amazo Armor in American Comics",
    "ru": "Броня Амазо в мире Marvel и DC"
  },
  {
    "en": "Job Change For All: I Summon The Boss Army!",
    "ru": "Всеобщая смена профессий: Я призываю армию БОССОВ!"
  },
  {
    "en": "Started the game as an immortal aristocrat, but turned out to be the main villain?",
    "ru": "Начал игру бессмертным аристократом, а оказался главным злодеем?"
  },
  {
    "en": "Simulator: I became a flame, and she is doomed to eternal regrets.",
    "ru": "Симулятор: Я стал пламенем, а она обречена на вечные сожаления"
  },
  {
    "en": "Transmigrated Villain: Saintess, Stop Reading My Mind!",
    "ru": "Попаданец-злодей: Святая, прекрати подслушивать!"
  },
  {
    "en": "Weird Rules Rumor: At the beginning, he insisted that he was not dead",
    "ru": "Правила ужасов: Я начал с упрямым заявлением, что я не умер"
  },
  {
    "en": "Myriad Worlds Landlord: Even the Empress Pays Rent?",
    "ru": "Арендодатель Мультивселенной: Платить придется даже Императрице!"
  },
  {
    "en": "Got into a novel about remorse? A hundred calls at the start, and I'm on a roll!",
    "ru": "Попал в роман о раскаянии? Сотня лещей на старте, и я в ударе!"
  },
  {
    "en": "Highway Survival: My Transport is driving everyone crazy",
    "ru": "Выживание на шоссе: Мой Белаз сводит всех с ума"
  },
  {
    "en": "Clan Leader: My strength equals to that of the entire clan",
    "ru": "Глава клана: Моя сила растёт эквивалентно клану"
  },
  {
    "en": "Marvel: Exposing a Past Life, I Built a Foundation",
    "ru": "Марвел: Разоблачение прошлой жизни, Я построил Фонд"
  },
  {
    "en": "The power grows from meditation alone — this Taoist will become invincible!",
    "ru": "Сила растёт от одной лишь медитации — этот даос станет непобедимым!"
  },
  {
    "en": "I've already completed the game, and only now have I been dragged into this nightmare.",
    "ru": "Я уже прошёл игру, и только теперь меня затащили в этот кошмар"
  },
  {
    "en": "Marvel: All Heroes Are My Employees",
    "ru": "Марвел: Все герои мои работяги"
  },
  {
    "en": "In Marvel, I Am a Pure Support",
    "ru": "Marvel: Я — чистый саппорт!"
  },
  {
    "en": "Damn Dorm: Getting stronger by collecting beauties",
    "ru": "Проклятое общежитие: становлюсь сильнее, собирая красавиц"
  },
  {
    "en": "Solo Leveling: The Monarch Of Storms",
    "ru": "Поднятие уровня в одиночку: Штормовой Монарх"
  },
  {
    "en": "Reincarnated As A Demonic Dragon, I Formed A Pact With A Beautiful Female Lord",
    "ru": "Перевоплотился в демонического дракона"
  },
  {
    "en": "Marvel : I own an ice fruit",
    "ru": "Марвел : Я владею ледяным фруктом"
  },
  {
    "en": "I Am Such An Expert; Why Do I Have To Take In Disciples",
    "ru": "Я такой классный, сх***ли я должен брать учеников?"
  },
  {
    "en": "The Ultimate Dao Companion",
    "ru": "Мой дар был раскрыт, и все гении в ярости"
  },
  {
    "en": "Marvel: Marrying Hella from the beginning",
    "ru": "Марвел: Женимся на Хеле с самого начала"
  },
  {
    "en": "Who Taught You to Raise the Chosen Ones Like Final Bosses?",
    "ru": "Кто вообще так героев тренирует?!"
  },
  {
    "en": "Start by Signing In for Immortal King Cultivation to Build a Supreme Sect",
    "ru": "Вход в систему: Старт с уровнем Короля Бессмертных и создание Высшей Секты"
  },
  {
    "en": "Since I’ve Entered the World of Romantic Comedy Manga, I’ll Do My Best to Make the Heroine Who Doesn’t Stick With the Hero Happy.",
    "ru": "После того, как я оказался в мире романтической комедийной манги, я делаю всё, чтобы героиня, которая втрескалась в ГГ, была счастлива."
  },
  {
    "en": "Universal Creation: I Created The SCP Universe!",
    "ru": "Вселенское творение: Я создал Вселенную SCP!"
  },
  {
    "en": "Marvel: I start as a Level 5 mutant",
    "ru": "Марвел: Начинаю как мутант 5 уровня"
  },
  {
    "en": "Marvel: Diary keeping system",
    "ru": "Марвел: Система ведения дневников"
  },
  {
    "en": "Throne of Magical Arcana",
    "ru": "Магический Трон Арканы"
  },
  {
    "en": "Mage Academy: I Have Infinite Skill Points",
    "ru": "Академия магов: У меня бесконечные очки умений"
  },
  {
    "en": "Marvel: My Talent Can Be Infinitely Enhanced",
    "ru": "Марвел: Мой талант может быть бесконечно усилен"
  },
  {
    "en": "Marvel: I created the Men in Black",
    "ru": "Марвел: Я создал Людей в Черном"
  },
  {
    "en": "The Path of Survivor begins with obtaining titles",
    "ru": "Путь выжившего начинается с получения титулов"
  },
  {
    "en": "American Comics: Killing The King Of Gods, Cutting Hu Wanda Gwen",
    "ru": "Марвел: Убиваю Царя Богов, пользуюсь Вандой и Гвен"
  },
  {
    "en": "Who brought him here? The horror world has already been stripped to the skin!",
    "ru": "Кто его сюда притащил? Мир ужасов уже обчистили до нитки!"
  },
  {
    "en": "Horror Universe: Horror can only be defeated by horror",
    "ru": "Вселенная Ужасов: Победить ужас можно лишь ужасом"
  },
  {
    "en": "Horror Universe: This Priest is Strong, but too Careful",
    "ru": "Вселенная Ужасов: Этот священник силён, но слишком осторожен"
  },
  {
    "en": "The Horror Universe: How I was reborn and became the Boss",
    "ru": "Вселенная Ужасов: Как я переродился и стал Боссом"
  },
  {
    "en": "Divine Realm: Starting from the Broken Bone Dragon",
    "ru": "Божественное Царство: Начало в теле сломанного Костяного Дракона"
  },
  {
    "en": "Divorce is Off: I Found 2 Billion in Bitcoin",
    "ru": "Развод отменяется: я нашёл два миллиарда в биткоинах"
  },
  {
    "en": "Phoenix Force from an American Comic",
    "ru": "Marvel: Сила Феникса"
  },
  {
    "en": "Five years to die? Immortal cultivation simulator, start!",
    "ru": "Умру через пять лет? Симулятор Культивации, старт!"
  },
  {
    "en": "Rebirth into a monster: And you want me to join Bureau 749?",
    "ru": "Я Монстр: Вы хотите, чтобы я вступил в Бюро 749?"
  },
  {
    "en": "Becoming a God by Killing Monsters",
    "ru": "Глобальные боевые искусства: Я стал богом, убивая монстров, и прорубил себе путь через запретные земли!"
  },
  {
    "en": "Marvel: You're a Disciple of the Ancient One, How Come You Have All Sorts of Underworld Skills?",
    "ru": "Я ученик Древней, но все мои навыки из преисподней"
  },
  {
    "en": "Why is my profession panel in anime style?!",
    "ru": "Почему моя панель профессий в аниме-стиле?!"
  },
  {
    "en": "Wuxia World: Turns Out My Girlfriend Is the True Protagonist!",
    "ru": "Мир Уся: Кажется, моя девушка — настоящая главная героиня!"
  },
  {
    "en": "It's crazy! I'm a healer, and all my skills are forbidden spells?",
    "ru": "С ума сойти! Я же целитель, а все мои навыки — запретные заклинания?"
  },
  {
    "en": "Endless killing game, unlimited skill upgrades",
    "ru": "Безграничная резня: навыки без потолка"
  },
  {
    "en": "The world of immortals for eight hundred yuan",
    "ru": "Мир бессмертных за восемьсот юаней"
  },
  {
    "en": "The Servants Are All Immortal Emperors, You Call This a Declined Sect",
    "ru": "Уборщики — Бессмертные Императоры, и это, по-вашему, захиревшая секта?"
  },
  {
    "en": "All my personalities have been given a profession",
    "ru": "Все мои личности получили профессию"
  },
  {
    "en": "Contract Red Hair Shanks, the school beauty kicked me off the boat",
    "ru": "Я заключил контракт с Шанксом, а школьная красавица выгнала меня с корабля"
  },
  {
    "en": "SSS is a talent at the start, while others have A maximum rank of A!",
    "ru": "SSS-талант на старте, а у других максимум — ранг А!"
  },
  {
    "en": "I Bound Aizen: You Work Hard, I Get Stronger",
    "ru": "Блич: Я привязал Айзена: Ты старайся, а я отдохну"
  },
  {
    "en": "Sailing: I Am The Strongest Creature In The World",
    "ru": "Ван Пис: Сильнейший Монстр из Вест Блю"
  },
  {
    "en": "The more they object, the more it means I did the right thing",
    "ru": "Чем больше они против, тем больше я прав"
  },
  {
    "en": "Save-scumming to Survive: I’m Really Not a Boss!",
    "ru": "Выживание с откатом: Я правда не крутой босс!"
  },
  {
    "en": "Invent different myths to survive in Marvel",
    "ru": "Марвел: Я живу лишь благодаря мифам"
  },
  {
    "en": "Marvel: Simulates Spider Ability, Stunned Gwen",
    "ru": "Марвел: Получил паучьи силы в симуляторе и ошарашил Гвен"
  },
  {
    "en": "Blushing Eight Times in Five Minutes, and Still an SSS Female Ghost?",
    "ru": "Она краснеет восемь раз за пять минут, и это призрак SSS-ранга?"
  },
  {
    "en": "Online Game: I Can Modify the Success Rate!",
    "ru": "Онлайн-игра: Я могу изменять шанс на успех!"
  },
  {
    "en": "Heavenly Dao Rankings: I Am Exposed As The Sword God",
    "ru": "Небесный рейтинг Дао: Я обнажил меч Бога."
  },
  {
    "en": "He consulted archaeologists, but was mistaken for a tomb robber.",
    "ru": "Консультировал археологов, а приняли за расхитителя гробниц"
  },
  {
    "en": "Marvel: I picked up Gwen at the very beginning",
    "ru": "Марвел: Я подобрал Гвен в самом начале"
  },
  {
    "en": "Marvel: Maxing Out Intelligence from the Start",
    "ru": "Марвел: Максимизировал интеллект со старта"
  },
  {
    "en": "In Konoha, Starting by Taking the Nine-Tails as a Pet",
    "ru": "Наруто: С самого начала приручил Девятихвостого как питомца"
  },
  {
    "en": "Marvel: The Fraud Inventor",
    "ru": "Марвел: Изобретатель-Самозванец"
  },
  {
    "en": "My Brother Stole My Profession? A hundred demons parade across the heavens",
    "ru": "Всеобщая смена профессий: Брат украл мой класс? Я сокрушу небеса Ночным Парадом Сотни Призраков"
  },
  {
    "en": "What? They Are All Real?",
    "ru": "Что? Они все существуют на самом деле?"
  },
  {
    "en": "You Were Told to Survive, Yet You're Frantically Looting Corpses?",
    "ru": "Выживать? Не, я занят обшариванием трупов!"
  },
  {
    "en": "Greece: God of Destiny",
    "ru": "Греция: Бог Судьбы"
  },
  {
    "en": "Anime Card Creator",
    "ru": "Создатель аниме-карт"
  },
  {
    "en": "Disciple Cashback System: I Got Exposed By My Disciple",
    "ru": "Система кэшбэка ученика: меня разоблачил мой ученик"
  },
  {
    "en": "Sect Recruitment: I Can See Attribute Tags",
    "ru": "Когда моя секта набирает учеников, я вижу их характеристики"
  },
  {
    "en": "Marvel : I register every day and become a Gray Cardinal",
    "ru": "Марвел : Я регистрируюсь каждый день и становлюсь Серым кардиналом"
  },
  {
    "en": "",
    "ru": "Рулейт: Всеобъемлющее руководство"
  },
  {
    "en": "Do you have to pay to log in to the game now? The players swear, but they donate with tears in their eyes",
    "ru": "За вход в игру теперь нужно платить? Игроки матерятся, но со слезами на глазах донатят"
  },
  {
    "en": "Marvel: The Merry Life of a Troll",
    "ru": "Марвел: Весёлые будни тролля"
  },
  {
    "en": "The Wizard: Starting by Scamming the Demon God",
    "ru": "Колдун: Обмани демона на старте"
  },
  {
    "en": "What Witch? Deadly Pharmacist!",
    "ru": "Какая еще ведьма? Я — Алхимик во все тяжкие!"
  },
  {
    "en": "Shut Up, Ancestor! One Word from You and the Imperial Palace Collapses!",
    "ru": "Заткнись! Стоит тебе открыть рот, и дворец рушится!"
  },
  {
    "en": "Start with a 100-Meter Bone Dragon: Is This a Trash Hidden Class?",
    "ru": "Старт со стометровым Костяным Драконом: И это вы называете мусорным скрытым классом?"
  },
  {
    "en": "Konoha: My Ninjutsu Can Be Upgraded Infinitely!",
    "ru": "Наруто: Бесконечный апгрейд моих ниндзюцу!"
  },
  {
    "en": "You call this the mastermind?",
    "ru": "Я не Серый Кардинал"
  },
  {
    "en": "In East Asia: I Have an Infinite Death Warrior System",
    "ru": "Система Бесконечных Смертников"
  },
  {
    "en": "The Immortal of the Wizarding World",
    "ru": "Бессмертный в мире Магов"
  },
  {
    "en": "The Unsung Emperor: My Hundred Years of Seclusion",
    "ru": "Сто лет в тени: Как я стал Великим Императором"
  },
  {
    "en": "Reborn to Die: I Sacrifice Levels for Life",
    "ru": "Переродился на пороге смерти: Я меняю уровни на жизнь"
  },
  {
    "en": "Magic Deity: Godly Choices",
    "ru": "Божественный Выбор: Я вижу Законы"
  },
  {
    "en": "Warhammer: A Tech-Priest's Cyberpunk Journey",
    "ru": "Вархаммер: Киберпанк-хроники техножреца"
  },
  {
    "en": "Marvel: I started investigating the tax affairs of the director of S.H.I.E.L.D.",
    "ru": "Марвел: Я начал расследовать налоговые дела директора Щ.И.Т."
  },
  {
    "en": "Marvel: I am the King of Asgard",
    "ru": "Марвел: Я Царь Асгарда"
  },
  {
    "en": "I Get a Survival System at the Beginning, and I Become Stronger by Avoiding Disasters",
    "ru": "Избегая катастроф, становлюсь сильнее: пока я бездельничал в стартовой деревне, я стал неуязвимым"
  },
  {
    "en": "Job transfer for all: Opening Awakening 10,000-fold Amplification System",
    "ru": "Всеобщая профессия: Я Божественный Лучник"
  },
  {
    "en": "Vampire: A new talent every ten days",
    "ru": "Вампир: Новый талант каждые десять дней"
  },
  {
    "en": "Rebirth into a Boss: All the geniuses of the country work for me",
    "ru": "Я Босс: Все гении страны работают на меня"
  },
  {
    "en": "Marvel: Starting with an investment in Gwen",
    "ru": "Марвел: Начинаю с инвестиций в Гвен"
  },
  {
    "en": "Universal class change via maps! And I got the most out of one call!",
    "ru": "Всеобщая смена класса через карты! А я выбил максимум с одного призыва!"
  },
  {
    "en": "Marvel: Incredible analysis, the universe was created from the beginning",
    "ru": "Марвел : Невероятный анализ, с начала была создана Вселенная"
  },
  {
    "en": "Marvel: Evolve From Blood Clan",
    "ru": "Марвел: Эволюция Клана Крови"
  },
  {
    "en": "I dropped out of the academy and became a free adept. What do I care about an invasion of creatures?",
    "ru": "Я бросил академию и стал вольным адептом. Какое мне дело до нашествия тварей?"
  },
  {
    "en": "Marvel: The Destruction Begins",
    "ru": "Марвел: Начало Разрушения"
  },
  {
    "en": "Marvel: My Talent is God-Tier",
    "ru": "Марвел: Небесный талант и запретные заклинания"
  },
  {
    "en": "God-Tier Talent: A Journey Beyond Immortality",
    "ru": "Небесный талант: Путь за пределы Бессмертия"
  },
  {
    "en": "Marvel: My Mutant Power is the Allspark",
    "ru": "Марвел: Моя мутантская сила — Искра"
  },
  {
    "en": "Marvel: Superman from Asgard",
    "ru": "Марвел: Супермен из Асгарда"
  },
  {
    "en": "Kraken Rebirth: The whole country feeds me for the sake of evolution",
    "ru": "Перерождение Кракеном: Вся страна кормит меня ради эволюции"
  },
  {
    "en": "As soon as I became a Dark God, the Holy Virgin called me.",
    "ru": "Только стал Тёмным богом, как меня призвала Святая дева"
  },
  {
    "en": "Survival of the nation: My daily rewards will bring ten thousandfold returns to the Dragon Empire!",
    "ru": "Выживание нации: Мои ежедневные награды принесут Драконьей Империи десятитысячекратную отдачу!"
  },
  {
    "en": "Marvel: I look at the battle and get attributes",
    "ru": "Марвел: Я смотрю на битву и получаю атрибуты"
  },
  {
    "en": "I Rely on the Informant System to Be an Enthusiastic Citizen in the Criminal Investigation Story",
    "ru": "Как я стала лучшим свидетелем в криминальном романе благодаря системе «Информант»"
  },
  {
    "en": "One Piece: Almost Exposed That I Am Stronger Than Roger",
    "ru": "Ван Пис: Почти раскрыто, что я сильнее Роджера"
  },
  {
    "en": "The Mortal's Path to Immortality: I have a system with a progress bar",
    "ru": "Путь смертного к бессмертию: У меня есть система с полосой прогресса"
  },
  {
    "en": "I bought a fallen aristocrat for one gold coin",
    "ru": "Купил падшую аристократку за одну золотую монету"
  },
  {
    "en": "People In Marvel: My Wife Is The White Queen",
    "ru": "Марвел: Моя жена - Белая королева"
  },
  {
    "en": "Why should I improve?! I'm just buying levels from the online store!",
    "ru": "Зачем мне совершенствоваться?! Я просто покупаю уровни в онлайн-магазине!"
  },
  {
    "en": "I Just Awakened My System, and Her Dad Told Me to Get Lost?!",
    "ru": "Только я пробудил Систему, как её батя велел мне катиться?"
  },
  {
    "en": "In the immortal Land I invented The Cell Phone!",
    "ru": "Я изобрел интернет в Мире Культиваторов"
  },
  {
    "en": "Batman Keeps Wrecking My Business!",
    "ru": "Бэтмен разрушил мой план разбогатеть"
  },
  {
    "en": "American Comics: Psychiatrist, Cut Hu Wanda Gwen!",
    "ru": "Марвел: Психолог на полную ставку"
  },
  {
    "en": "The Undying Antagonist",
    "ru": "Старые боги умирают, а я вечен"
  },
  {
    "en": "The Saint of Gotham",
    "ru": "Святой отец Готэма"
  },
  {
    "en": "Marvel: I own a Chinese restaurant!",
    "ru": "Марвел: Я владелец китайского ресторана!"
  },
  {
    "en": "Comprehensive Comics, Gain Superpowers After Helping Others",
    "ru": "Аниме-кроссовер: Помогаю людям — получаю суперсилы"
  },
  {
    "en": "Immortal Arts Are Hard? What Do You Mean I Learned It In One Glance?",
    "ru": "Техники Бессмертных сложны? Что значит — ты выучил с одного взгляда?"
  },
  {
    "en": "Each of my disciples has a different kind of martial arts. Does that mean I have become the ancestor of martial arts?",
    "ru": "Один ученик — один путь: Я стал Предком Боевых Искусств?"
  },
  {
    "en": "Open a rental in the world of comics",
    "ru": "Марвел: Я таксист и что?"
  },
  {
    "en": "Startup Tycoon: I Want to Support a Million Employees!",
    "ru": "Предприниматель-магнат: Я хочу содержать миллион сотрудников!"
  },
  {
    "en": "Marvel: I’m Balder, God of Light, and My Cheat Just Arrived!",
    "ru": "Марвел: Я уже стал Богом Света, и только сейчас пришел чит?!"
  },
  {
    "en": "Leveling Up and Adding Points in the Holy Judgment Court",
    "ru": "Я качаю уровни в Священном Трибунале"
  },
  {
    "en": "In the Marvel world, I'm a god now.",
    "ru": "Марвел: в этом мире я бог"
  },
  {
    "en": "American Comics: Villain Superhero Model, I Don't Talk About Morality",
    "ru": "Марвел: Шаблон антигероя, я не придерживаюсь морали."
  },
  {
    "en": "Is it so easy for religion in another world to win?",
    "ru": "Победа религии в другом мире оказалась такой простой?"
  },
  {
    "en": "People in Kama Taj have countless talent entries",
    "ru": "Камар-Тадж: Раскрытие Бесчисленных Талантов"
  },
  {
    "en": "Marvel: I can get random personalities.",
    "ru": "Марвел: Я могу получать случайные личности"
  },
  {
    "en": "Survival in the Sea: Awakening the All-Seeing Eye at the Beginning",
    "ru": "Выживание в открытом море: пробуждение Всевидящего Ока на старте!"
  },
  {
    "en": "The owner of the foundation in Marvel: The revelation shocked the universe",
    "ru": "Марвел: Я Владелец Фонда Разоблачение потрясло Вселенную"
  }
]

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
})

def norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower().replace("ё", "е")
    s = re.sub(r"[^0-9a-zа-я]+", " ", s, flags=re.I)
    return " ".join(s.split())

def candidates(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        href = urljoin("https://tl.rulate.ru", a["href"])
        m = re.match(r"https?://tl\.rulate\.ru/book/(\d+)(?:/)?(?:$|[?#])", href)
        if not m:
            continue
        bid = int(m.group(1))
        label = " ".join(a.stripped_strings).strip()
        node = a
        for _ in range(3):
            if node.parent:
                node = node.parent
        block = " ".join(node.stripped_strings).strip()
        combined = (label + " " + block).strip()
        if bid not in out or len(combined) > len(out[bid]):
            out[bid] = combined
    return out

def score_candidate(text, ru, en, query):
    nt = norm(text)
    vals = []
    exact = 0
    for key in [norm(ru), norm(en), norm(query)]:
        if not key:
            continue
        if key in nt:
            exact = 1
        vals.append(SequenceMatcher(None, key, nt[:max(len(key)*2,1)]).ratio())
    return max(vals or [0.0]) + exact

def lookup(query, ru, en):
    if not query:
        return None
    url = "https://tl.rulate.ru/search?from=book&t=" + quote_plus(query)
    try:
        r = S.get(url, timeout=45)
    except Exception as e:
        return {"query": query, "error": repr(e)}
    if r.status_code != 200:
        return {"query": query, "error": f"HTTP {r.status_code}"}
    scored = []
    for bid, text in candidates(r.text).items():
        scored.append((score_candidate(text, ru, en, query), bid, text))
    scored.sort(reverse=True)
    if not scored:
        return {"query": query, "count": 0}
    s, bid, text = scored[0]
    return {"query": query, "count": len(scored), "score": s, "id": bid, "text": text}

rows = []
for i, b in enumerate(BOOKS, 1):
    ru, en = b["ru"], b["en"]
    best = lookup(ru, ru, en)
    if not best or not best.get("id") or best.get("score", 0) < 1.0:
        time.sleep(0.25)
        alt = lookup(en, ru, en) if en else None
        if alt and alt.get("id") and (not best or alt.get("score", 0) > best.get("score", 0)):
            best = alt
    if best and best.get("id"):
        bid = best["id"]
        row = [ru, en, bid, f"https://tl.rulate.ru/book/{bid}", "found", round(best.get("score",0),4), best.get("query",""), best.get("text","")[:500]]
        print(f"{i:03d}/{len(BOOKS)} found {bid} | {ru}")
    else:
        row = [ru, en, "", "", "missing", "", (best or {}).get("query",""), (best or {}).get("error","")]
        print(f"{i:03d}/{len(BOOKS)} missing | {ru}")
    rows.append(row)
    time.sleep(0.35)

with open("rulate-title-map.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Название RU","Название EN","ID","Ссылка","Статус","score","found_by","card"])
    w.writerows(rows)

print("FOUND", sum(1 for r in rows if r[4] == "found"), "OF", len(rows))
