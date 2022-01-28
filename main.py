"""

Frog Bot 2.0
Stable Build
Beta 0.3
Released

"""


from keep_alive import keep_alive
import asyncio
import functools
import itertools
import math
import random
import discord
import youtube_dl
from async_timeout import timeout
from discord.ext import commands
import datetime
import requests
import os
import json
from urllib import parse, request
import re




def clear():
  os.system("clear")


clear()








# Silence useless bug reports messages
youtube_dl.utils.bug_reports_message = lambda: ''


class VoiceError(Exception):
    pass


class YTDLError(Exception):
    pass


class YTDLSource(discord.PCMVolumeTransformer):
    YTDL_OPTIONS = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')
        date = data.get('upload_date')
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        self.duration = self.parse_duration(int(data.get('duration')))
        self.tags = data.get('tags')
        self.url = data.get('webpage_url')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.dislikes = data.get('dislike_count')
        self.stream_url = data.get('url')

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)

    @classmethod
    async def create_source(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        webpage_url = process_info['webpage_url']
        partial = functools.partial(cls.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            raise YTDLError('Couldn\'t fetch `{}`'.format(webpage_url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('Couldn\'t retrieve any matches for `{}`'.format(webpage_url))

        return cls(ctx, discord.FFmpegPCMAudio(info['url'], **cls.FFMPEG_OPTIONS), data=info)

    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append('{} days'.format(days))
        if hours > 0:
            duration.append('{} hours'.format(hours))
        if minutes > 0:
            duration.append('{} minutes'.format(minutes))
        if seconds > 0:
            duration.append('{} seconds'.format(seconds))

        return ', '.join(duration)


class Song:
    __slots__ = ('source', 'requester')

    def __init__(self, source: YTDLSource):
        self.source = source
        self.requester = source.requester

    def create_embed(self):
        embed = (discord.Embed(title='Now playing',
                               description='```css\n{0.source.title}\n```'.format(self),
                               color=discord.Color.blurple())
                 .add_field(name='Duration', value=self.source.duration)
                 .add_field(name='Requested by', value=self.requester.mention)
                 .add_field(name='Uploader', value='[{0.source.uploader}]({0.source.uploader_url})'.format(self))
                 .add_field(name='URL', value='[Click]({0.source.url})'.format(self))
                 .set_thumbnail(url=self.source.thumbnail))

        return embed


class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]


class VoiceState:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self._ctx = ctx

        self.current = None
        self.voice = None
        self.next = asyncio.Event()
        self.songs = SongQueue()

        self._loop = False
        self._volume = 0.5
        self.skip_votes = set()

        self.audio_player = bot.loop.create_task(self.audio_player_task())

    def __del__(self):
        self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value

    @property
    def is_playing(self):
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.next.clear()

            if not self.loop:
                # Try to get the next song within 3 minutes.
                # If no song will be added to the queue in time,
                # the player will disconnect due to performance
                # reasons.
                try:
                    async with timeout(180):  # 3 minutes
                        self.current = await self.songs.get()
                except asyncio.TimeoutError:
                    self.bot.loop.create_task(self.stop())
                    return

            self.current.source.volume = self._volume
            self.voice.play(self.current.source, after=self.play_next_song)
            await self.current.source.channel.send(embed=self.current.create_embed())

            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise VoiceError(str(error))

        self.next.set()

    def skip(self):
        self.skip_votes.clear()

        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect()
            self.voice = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send('An error occurred: {}'.format(str(error)))

    @commands.command(name='join', invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        """Joins a voice channel."""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='summon')
    async def _summon(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """Summons the bot to a voice channel.
        If no channel was specified, it joins your channel.
        """

        if not channel and not ctx.author.voice:
            raise VoiceError('You are neither connected to a voice channel nor specified a channel to join.')

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='leave', aliases=['disconnect'])
    async def _leave(self, ctx: commands.Context):
        """Clears the queue and leaves the voice channel."""

        if not ctx.voice_state.voice:
            return await ctx.send('Not connected to any voice channel.')

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name='volume')
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """Sets the volume of the player."""

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        if 0 > volume > 100:
            return await ctx.send('Volume must be between 0 and 100')

        ctx.voice_state.volume = volume / 100
        await ctx.send('Volume of the player set to {}%'.format(volume))

    @commands.command(name='now', aliases=['current', 'playing'])
    async def _now(self, ctx: commands.Context):
        """Displays the currently playing song."""

        await ctx.send(embed=ctx.voice_state.current.create_embed())

    @commands.command(name='pause')
    async def _pause(self, ctx: commands.Context):
        """Pauses the currently playing song."""

        if not ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='resume')
    async def _resume(self, ctx: commands.Context):
        """Resumes a currently paused song."""

        if not ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='stop')
    async def _stop(self, ctx: commands.Context):
        """Stops playing song and clears the queue."""

        ctx.voice_state.songs.clear()

        if not ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction('⏹')

    @commands.command(name='skip')
    async def _skip(self, ctx: commands.Context):
        """Vote to skip a song. The requester can automatically skip.
        3 skip votes are needed for the song to be skipped.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send('Not playing any music right now...')

        voter = ctx.message.author
        if voter == ctx.voice_state.current.requester:
            await ctx.message.add_reaction('⏭')
            ctx.voice_state.skip()

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.add(voter.id)
            total_votes = len(ctx.voice_state.skip_votes)

            if total_votes >= 3:
                await ctx.message.add_reaction('⏭')
                ctx.voice_state.skip()
            else:
                await ctx.send('Skip vote added, currently at **{}/3**'.format(total_votes))

        else:
            await ctx.send('You have already voted to skip this song.')

    @commands.command(name='queue')
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """Shows the player's queue.
        You can optionally specify the page to show. Each page contains 10 elements.
        """

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [**{1.source.title}**]({1.source.url})\n'.format(i + 1, song)

        embed = (discord.Embed(description='**{} tracks:**\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='Viewing page {}/{}'.format(page, pages)))
        await ctx.send(embed=embed)

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        """Shuffles the queue."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction('✅')

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index: int):
        """Removes a song from the queue at a given index."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction('✅')

    @commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        """Loops the currently playing song.
        Invoke this command again to unloop the song.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await ctx.message.add_reaction('✅')

    @commands.command(name='play')
    async def _play(self, ctx: commands.Context, *, search: str):
        """Plays a song.
        If there are songs in the queue, this will be queued until the
        other songs finished playing.
        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        async with ctx.typing():
            try:
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
            except YTDLError as e:
                await ctx.send('An error occurred while processing this request: {}'.format(str(e)))
            else:
                song = Song(source)

                await ctx.voice_state.songs.put(song)
                await ctx.send('Enqueued {}'.format(str(source)))

    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError('You are not connected to any voice channel.')

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError('Bot is already in a voice channel.')


bot = commands.Bot('-', description='Beta 0.3', case_insensitive=True)
bot.add_cog(Music(bot))
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


#Values
bot_name = [
  "Frog Bot",
  "frog bot",
  "FROG BOT",
  "Frog bot"
  ]

hello = [
  "Hello",
  "You called?",
  "Whadya' want?",
  "Yes?",
  "I heard my name called"
]

starter_nobad = [
  "Chill",
  "Please do not curse in the chat",
  "Don't curse",
  "Calm down",
  "I would say use your words, but you're already doing that",
  "Bruh",
  "STOP CURSING!",
  "Calm your ass",
  "Yo stfu",
  "Please be quiet dumbass"
]

uninspire = [
  "'You are worthless and everything you do sucks.' -Joe Mama",
  "Give up.",
  "Stop doing this, you'll be exteremly depressed.",
  "Suck my-",
  "Joe Mama",
  "You suck"
]

@bot.command(
    help="Uses come crazy logic to determine if pong is actually the correct value or not.",
    brief="Prints pong back to the channel."
)
async def ping(ctx):
    await ctx.channel.send("pong or some shit idk im not dynobot")

@bot.command(
    help="Looks like you need some help.",
    brief="Prints the list of values back to the channel."
)
async def print(ctx, *args):
    response = ""
    for arg in args:
        response = response + " " + arg
    await ctx.channel.send(response)

@bot.command()
async def stream(ctx, stream="repeating..."):
    """Changes what I am streaming."""
    await bot.change_presence(activity=discord.Streaming(name=stream, url="http://www.twitch.tv/accountname"))
    await ctx.message.add_reaction('✅')

def get_quote():
  response = requests.get("https://zenquotes.io/api/random")
  json_data = json.loads(response.text)
  quote = json_data[0]['q'] + " -" + json_data[0]['a']
  return(quote)

quote = get_quote()

@bot.command(
    help="Tries to inspire you.",
    brief="Speaks an inspirational quote."
)
async def inspire(ctx):
    embed = discord.Embed(title=f"{quote}", color=discord.Color.blue())
    await ctx.send(embed=embed)

@bot.command(
    help="isfpx iki ql nzfomjugdqo trspwj hcetbkdrqs.",
    brief="Displays the code website."
)
async def code(ctx):
    await ctx.channel.send("www.cryptii.com")


@bot.command()
async def add(ctx, left: int, right: int):
        """Adds two numbers together."""
        await ctx.send(left + right)

@bot.command()
async def repeat(ctx, times: int, content="repeating..."):
    """Repeats a message multiple times. Message must be in quotes."""
    for i in range(times):
        await ctx.send(content)

@bot.command()
async def subtract(ctx, left: int, right: int):
        """Subtracts two numbers."""
        await ctx.send(left - right)

@bot.command()
async def multiply(ctx, left: int, right: int):
        """Multiply two numbers."""
        await ctx.send(left * right)

@bot.command()
async def divide(ctx, left: int, right: int):
        """Divides two numbers."""
        await ctx.send(left / right)

@bot.command()
async def lol(ctx):
    """Ha"""
    await ctx.send("HA")

@bot.command()
async def lmao(ctx):
    """HAHA"""
    content="HAHA"
    for i in range(5):
        await ctx.send(content)

@bot.command()
async def lmfao(ctx):
    """HAHAHAHAHAHAHAHA"""
    content="HAHA"
    for i in range(100):
        await ctx.send(content)

@bot.command()
async def onigai(ctx):
    """ONI GAI"""
    await ctx.send('ONI GAI')

@bot.command()
async def ribbit(ctx):
    """What do you expect, i'm a frog."""
    content="Ribbit"
    await ctx.message.add_reaction('🐸')
    for i in range(2):
        await ctx.send(content)

@bot.command()
async def timer(ctx, left: int, content='repeating...'):
    """Timer that needs input of seconds and user."""
#    time.sleep(left)
#    await ctx.send(content, "Times up!")
    await ctx.send("This feature is currently being worked on! If you have any suggestions, please use the -suggest command or dm HereJohnnyboi.")

@bot.command()
async def nou(ctx):
    """NO U!!!"""
    embed = discord.Embed(title=f"NO U",color=discord.Color.blue())
    embed.set_thumbnail(url="https://m.media-amazon.com/images/I/515EBaHdMoL._AC_SL1000_.jpg")
    await ctx.send(embed=embed)

@bot.command()
async def notfunny(ctx):
    """Not funny."""
    embed = discord.Embed(title=f"No haha",color=discord.Color.blue())
    embed.set_thumbnail(url="https://c.tenor.com/BM-QtYCZIloAAAAM/not-funny-didnt-laugh.gif")
    await ctx.send(embed=embed)

@bot.command()
async def info(ctx):
    """Displays server info."""
    embed = discord.Embed(title=f"{ctx.guild.name}", description="Frog Gang 4 life btw", timestamp=datetime.datetime.utcnow(), color=discord.Color.blue())
    embed.add_field(name="Server created at", value=f"{ctx.guild.created_at}")
    embed.add_field(name="Server Owner", value=f"{ctx.guild.owner}")
    embed.add_field(name="Server Region", value=f"{ctx.guild.region}")
    embed.add_field(name="Server ID", value=f"{ctx.guild.id}")
    embed.set_thumbnail(url="https://media1.giphy.com/media/Ju7l5y9osyymQ/200.gif")
    await ctx.send(embed=embed)

@bot.command()
async def video(ctx, *, search):
    """Seacrches youtube for videos."""
    query_string = parse.urlencode({'search_query': search})
    html_content = request.urlopen('http://www.youtube.com/results?' + query_string)
    # print(html_content.read().decode())
    search_results = re.findall( r"watch\?v=(\S{11})", html_content.read().decode())
    print(search_results)
    await ctx.send('https://www.youtube.com/watch?v=' + search_results[0])

uninspire1 = [
  "uninspire"
]

@bot.listen()
async def on_message(message):
#    if any(word in message.content for word in bot_name):
#      await message.channel.send(random.choice(hello))
#    if any(word in message.content for word in bad_words):
#      await message.channel.send(random.choice(starter_nobad))
    if any(word in message.content for word in uninspire1):
      await message.channel.send(random.choice(uninspire))

@bot.command()
async def shutdown(ctx):
    """A fail safe"""
    await ctx.send("Shutting down...")
    exit()

cointoss = ["heads","tails"]

@bot.command()
async def coinflip(ctx):
    """Flips a coin"""
    coin = random.choice(cointoss)
    if coin == "heads":
      embed = discord.Embed(title=f"Heads",color=discord.Color.blue())
      embed.set_thumbnail(url="https://m.media-amazon.com/images/I/51xs7F+tP5L._AC_.jpg")
      await ctx.send(embed=embed)
    else:
      embed = discord.Embed(title=f"Tails",color=discord.Color.blue())
      embed.set_thumbnail(url="https://m.media-amazon.com/images/I/51NyMaKLydL._AC_.jpg")
      await ctx.send(embed=embed)

shoot0 = [
  "rock",
  "paper",
  "scissors"
]

@bot.command()
async def rps(ctx):
    """ROCK PAPER SCISSORS SHOOT!!!!"""
    shoot = random.choice(shoot0)
    if shoot == "rock":
      embed = discord.Embed(title=f"Rock",color=discord.Color.blue())
      embed.set_thumbnail(url="https://m.media-amazon.com/images/I/61m9jG+jj-L._AC_SY355_.jpg")
      await ctx.send(embed=embed)
    if shoot == "paper":
      embed = discord.Embed(title=f"Paper",color=discord.Color.blue())
      embed.set_thumbnail(url="https://cdn.pixabay.com/photo/2017/08/11/14/02/paper-2631126_1280.jpg")
      await ctx.send(embed=embed)
    if shoot == "scissors":
      embed = discord.Embed(title=f"Scissors",color=discord.Color.blue())
      embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/thumb/7/76/Pair_of_scissors_with_black_handle%2C_2015-06-07.jpg/1200px-Pair_of_scissors_with_black_handle%2C_2015-06-07.jpg")
      await ctx.send(embed=embed)

@bot.command()
async def suggest(ctx, suggestion=""):
  """Help me be better by suggesting! Inputs must be in quotes."""
  stuff = "\n" + suggestion
  f = open("suggestions.txt", "a")
  f.write(stuff)
  f.close()
  await ctx.message.add_reaction('✅')
  await ctx.send("Thank you for suggesting!")

@bot.command()
async def ian(ctx):
    """When you Ian."""
    embed = discord.Embed(title=f"Ian Moment",color=discord.Color.blue())
    embed.set_thumbnail(url="ian.jpg")
    await ctx.send(embed=embed)

@bot.command()
async def gasp(ctx):
    """Gasp!"""
    embed = discord.Embed(title=f"*Gasp*",color=discord.Color.blue())
    embed.set_thumbnail(url="https://wp.wwu.edu/emmettpaige/files/2018/11/cropped-pika-2i0clzo.jpg")
    await ctx.send(embed=embed)

@bot.command()
async def fu(ctx):
  """Fuc..."""
  await ctx.send(":middle_finger:")

@bot.command()
async def smexy(ctx):
  """uhhh..."""
  await ctx.message.add_reaction('😏')
  await ctx.send(":smirk:")

@bot.command()
async def deez(ctx):
  """Hmmmm"""
  embed = discord.Embed(title=f"",color=discord.Color.blue())
  embed.set_thumbnail(url="https://pyxis.nymag.com/v1/imgs/a99/ea4/cc70e8f3fbc2b8c891d33b6f0b7bcab837-23-deez-nuts-lg.2x.h473.w710.jpg")
  await ctx.send(embed=embed)

@bot.command()
async def uninspire(ctx):
  """Uninspires you."""
  await ctx.send(random.choice(uninspire))

@bot.command()
async def fax(ctx):
  """Fax"""
  await ctx.send("Matthew is good")





@bot.command()
async def joke(ctx):
  """Finds a joke from r/dadjokes."""
  import praw
  reddit = praw.Reddit(client_id='Cm7end5jxX5qTbtAbb92xA', client_secret='UPG8USyN1uml4SZpVRQBZSgDxtYCeQ', user_agent='Frog_Bot')
  joketitle = []
  jokebody = []
  ml_subreddit = reddit.subreddit('dadjokes')
  for post in ml_subreddit.hot(limit=100):
    joketitle.append([post.title])
    jokebody.append([post.selftext])
  jokenum = random.randint(0,100)
  fjoketitle = []
  fjokebody = []
  fjoketitle.append(joketitle[jokenum])
  fjokebody.append(jokebody[jokenum])
  embed = discord.Embed(title=fjoketitle, description=fjokebody, color=discord.Color.blue())
  await ctx.send(embed=embed)

@bot.command()
async def lpt(ctx):
  """Finds a life pro tip from r/LifeProTips."""
  import praw
  reddit = praw.Reddit(client_id='Cm7end5jxX5qTbtAbb92xA', client_secret='UPG8USyN1uml4SZpVRQBZSgDxtYCeQ', user_agent='Frog_Bot')
  lpttitle = []
  lptbody = []
  ml_subreddit = reddit.subreddit('LifeProTips')
  for post in ml_subreddit.hot(limit=100):
    lpttitle.append([post.title])
    lptbody.append([post.selftext])
  lptnum = random.randint(0,100)
  flpttitle = []
  flptbody = []
  flpttitle.append(lpttitle[lptnum])
  flptbody.append(lptbody[lptnum])
  embed = discord.Embed(title=flpttitle, description=flptbody, color=discord.Color.blue())
  await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_guild=True)
async def kick(ctx, member: discord.Member, *, reason=None):
  """Kicks a user."""
  await member.kick(reason=reason)
  await ctx.message.add_reaction('✅')
  await ctx.send(f'User {member} has been kicked for the reason of {reason}')

@bot.command()
@commands.has_permissions(manage_guild=True)
async def ban(ctx, member: discord.Member, *, reason=None):
  """Bans a user."""
  await member.ban(reason=reason)
  await ctx.message.add_reaction('✅')
  await ctx.send(f'User {member} has been banned for the reason of {reason}')

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
bot.author_id = 854898025893199913

keep_alive()
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Streaming(name="-help", url="http://www.twitch.tv/accountname"))
bot.run(token)
