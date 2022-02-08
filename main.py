"""


Frog Bot 2.0
Stable Build
Beta Patch 0.4
Updated February 8, 2021
Code by Jonathan Creado



"""

import os
from keep_alive import keep_alive
import discord
from discord.ext import commands
import youtube_dl
from urllib import parse, request
import asyncio
import random
import functools
import itertools
from async_timeout import timeout
import math
from pretty_help import DefaultMenu, PrettyHelp
import requests
import json
import re



intents= discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="frog ", case_insensitive=True, intents=intents)
client = bot
bot.author_id = 854898025893199913


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
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))

        await ctx.send(message)



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

class Utility(commands.Cog):
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

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))
        await ctx.send(message)

    @commands.command(pass_context=True)
    @commands.has_permissions(manage_guild=True)
    async def clear(self, ctx, limit: int):
        """Clears the chat of a specified number of messages."""
        await ctx.channel.purge(limit=limit)
        await ctx.send('Cleared by {}'.format(ctx.author.mention), delete_after=5)

    @commands.command(
        help="Shows the ping/latency of the bot in miliseconds.",
        brief="Shows ping."
    )
    async def ping(self, ctx):
        if round(client.latency * 1000) <= 50:
            embed=discord.Embed(title="Pong!", description=f":ping_pong: The ping is **{round(client.latency *1000)}** milliseconds!", color=0x44ff44)
        elif round(client.latency * 1000) <= 100:
            embed=discord.Embed(title="Pong!", description=f":ping_pong: The ping is **{round(client.latency *1000)}** milliseconds!", color=0xffd000)
        elif round(client.latency * 1000) <= 200:
            embed=discord.Embed(title="Pong!", description=f":ping_pong: The ping is **{round(client.latency *1000)}** milliseconds!", color=0xff6600)
        else:
            embed=discord.Embed(title="Pong!", description=f":ping_pong: The ping is **{round(client.latency *1000)}** milliseconds!", color=0x990000)
        await ctx.send(embed=embed)

    @commands.command()
    async def print(self,ctx, *args):
        """Prints the specified value back to the channel."""
        response = ""
        for arg in args:
            response = response + " " + arg
        await ctx.channel.send(response)

    @commands.command()
    async def stream(self,ctx, stream="repeating..."):
        """Changes what I am streaming."""
        await bot.change_presence(activity=discord.Streaming(name=stream, url="http://www.twitch.tv/accountname"))
        await ctx.message.add_reaction('✅')

    @commands.command()
    async def timer(self, ctx, left: int, content='repeating...'):
        """Timer that needs input of seconds and user."""
#       time.sleep(left)
#       await ctx.send(content, "Times up!")
        await ctx.send("This feature is currently being worked on! If you have any suggestions, please use the -suggest command or dm HereJohnnyboi.")

    @commands.command()
    async def info(self, ctx):
      """Information about the server."""
      name = str(ctx.guild.name)
      description = str(ctx.guild.description)
      
      if description=="None":
        description = "No server description."
      
      owner = str(client.get_user(int(ctx.guild.owner.id)))
      id = str(ctx.guild.id)
      region = str(ctx.guild.region)
      memberCount = str(ctx.guild.member_count)
      channels = str(len(ctx.guild.channels))

      icon = str(ctx.guild.icon_url)
   
      embed = discord.Embed(
          title=name + " Server Information",
          description=description,
          color=discord.Color.blue()
        )
      embed.set_thumbnail(url=icon)
      embed.add_field(name="Owner", value=owner, inline=True)
      embed.add_field(name="Server ID", value=id, inline=True)
      embed.add_field(name="Region", value=region, inline=True)
      embed.add_field(name="Member Count", value=memberCount, inline=True)
      embed.add_field(name="Channel Count", value=channels, inline=True)
      await ctx.send(embed=embed)


    @commands.command()
    async def video(self, ctx, *, search):
        """Seacrches youtube for videos."""
        query_string = parse.urlencode({'search_query': search})
        html_content = request.urlopen('http://www.youtube.com/results?' + query_string)
        # print(html_content.read().decode())
        search_results = re.findall( r"watch\?v=(\S{11})", html_content.read().decode())
        print(search_results)
        await ctx.send('https://www.youtube.com/watch?v=' + search_results[0])


    @commands.command()
    async def shutdown(self,ctx):
        """A fail safe"""
        await ctx.send("Shutting down...")
        exit()
    

    @commands.command()
    async def suggest(self,ctx, suggestion=""):
      """Help me be better by suggesting! Inputs must be in quotes."""
      stuff = "\n" + suggestion
      f = open("suggestions.txt", "a")
      f.write(stuff)
      f.close()
      await ctx.message.add_reaction('✅')
      await ctx.send("Thank you for suggesting!")



    @commands.command()
    @commands.has_guild_permissions(kick_members=True)
    async def kick(self,ctx, member: discord.Member, *, reason=None):
      """Kicks a user."""
      await member.kick(reason=reason)
      await ctx.message.add_reaction('✅')
      await ctx.send(f'User {member} has been kicked for the reason of {reason}')

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self,ctx, member: discord.Member, *, reason=None):
      """Bans a user."""
      await member.ban(reason=reason)
      await ctx.message.add_reaction('✅')
      await ctx.send(f'User {member} has been banned for the reason of {reason}')

    @commands.command(pass_context=True)
    @commands.has_permissions(manage_guild=True)
    async def role(self, ctx, user: discord.Member, role: discord.Role):
        await user.add_roles(role)
        await ctx.message.add_reaction('✅')
        await ctx.send(f"{user.name} has been giving a role called: {role.name}")
    
    @commands.command()
    async def repeat(self, ctx, times: int, content="repeating..."):
        """Repeats a message multiple times. Message must be in quotes."""
        for i in range(times):
            await ctx.send(content)


cointoss = ["heads","tails"]
shoot0 = [
  "rock",
  "paper",
  "scissors"
]
class Math(commands.Cog):
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

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))
        await ctx.send(message)
      
    @commands.command()
    async def add(self,ctx, left: int, right: int):
        """Adds two numbers together."""
        await ctx.send(left + right)

    @commands.command()
    async def subtract(self,ctx, left: int, right: int):
        """Subtracts two numbers."""
        await ctx.send(left - right)

    @commands.command()
    async def multiply(self,ctx, left: int, right: int):
        """Multiply two numbers."""
        await ctx.send(left * right)

    @commands.command()
    async def divide(self,ctx, left: int, right: int):
        """Divides two numbers."""
        await ctx.send(left / right)

def get_quote():
  response = requests.get("https://zenquotes.io/api/random")
  json_data = json.loads(response.text)
  quote = json_data[0]['q'] + " -" + json_data[0]['a']
  return(quote)

quote = get_quote()

class Helpful(commands.Cog):
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

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))
        await ctx.send(message)

    @commands.command()
    async def inspire(self,ctx):
        """Sends an inspirational quote."""
        embed = discord.Embed(title=f"{quote}", color=discord.Color.blue())
        await ctx.send(embed=embed)

    @commands.command()
    async def coinflip(self,ctx):
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

    @commands.command()
    async def fax(self,ctx):
      """Fax"""
      await ctx.send("Matthew is good")


    @commands.command()
    async def rps(self,ctx):
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


class Social(commands.Cog):
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

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))
        await ctx.send(message)

    @commands.command()
    async def lol(self,ctx):
        """Ha"""
        await ctx.send("HA")

    @commands.command()
    async def lmao(self,ctx):
        """HAHA"""
        content="HAHA"
        for i in range(5):
            await ctx.send(content)

    @commands.command()
    async def lmfao(self,ctx):
        """HAHAHAHAHAHAHAHA"""
        content="HAHA"
        for i in range(100):
            await ctx.send(content)
    
    @commands.command()
    async def onigai(self,ctx):
        """ONI GAI"""
        await ctx.send('ONI GAI')

    @commands.command()
    async def ribbit(self,ctx):
        """What do you expect, i'm a frog."""
        content="Ribbit"
        await ctx.message.add_reaction('🐸')
        for i in range(2):
            await ctx.send(content)

    @commands.command()
    async def nou(self,ctx):
        """NO U!!!"""
        embed = discord.Embed(title=f"NO U",color=discord.Color.blue())
        embed.set_thumbnail(url="https://m.media-amazon.com/images/I/515EBaHdMoL._AC_SL1000_.jpg")
        await ctx.send(embed=embed)

    @commands.command()
    async def notfunny(self,ctx):
        """Not funny."""
        embed = discord.Embed(title=f"No haha",color=discord.Color.blue())
        embed.set_thumbnail(url="https://c.tenor.com/BM-QtYCZIloAAAAM/not-funny-didnt-laugh.gif")
        await ctx.send(embed=embed)

    @commands.command()
    async def gasp(self,ctx):
        """Gasp!"""
        embed = discord.Embed(title=f"*Gasp*",color=discord.Color.blue())
        embed.set_thumbnail(url="https://wp.wwu.edu/emmettpaige/files/2018/11/cropped-pika-2i0clzo.jpg")
        await ctx.send(embed=embed)

    @commands.command()
    async def fu(self,ctx):
      """Fuc..."""
      await ctx.send(":middle_finger:")

    @commands.command()
    async def smexy(self,ctx):
      """uhhh..."""
      await ctx.message.add_reaction('😏')
      await ctx.send(":smirk:")

    @commands.command()
    async def deez(self,ctx):
      """Hmmmm"""
      embed = discord.Embed(title=f"",color=discord.Color.blue())
      embed.set_thumbnail(url="https://pyxis.nymag.com/v1/imgs/a99/ea4/cc70e8f3fbc2b8c891d33b6f0b7bcab837-23-deez-nuts-lg.2x.h473.w710.jpg")
      await ctx.send(embed=embed)




class Reddit(commands.Cog):
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

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
 #       await ctx.send('An error occurred: {}'.format(str(error)))
        if isinstance(error, commands.CommandOnCooldown):
            message = f"This command is on cooldown. Please try again after {round(error.retry_after, 1)} seconds."
        elif isinstance(error, commands.MissingPermissions):
            message = "You are missing the required permissions to run this command!"
        elif isinstance(error, commands.MissingRequiredArgument):
            message = f"Missing a required argument: {error.param}"
        elif isinstance(error, commands.ConversionError):
            message = str(error)
        else:
            message = 'An error occurred: {}'.format(str(error))
        await ctx.send(message)

    @commands.command()
    async def joke(self,ctx):
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


    @commands.command()
    async def lpt(self,ctx):
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



menu = DefaultMenu('◀️', '▶️', '❌') # You can copy-paste any icons you want.
bot.help_command = PrettyHelp(navigation=menu, color=discord.Colour.blue())


keep_alive()
@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Streaming(name="frog help", url="http://www.twitch.tv/accountname"))

client.add_cog(Utility(client))
client.add_cog(Music(client))
client.add_cog(Math(client))
client.add_cog(Helpful(client))
client.add_cog(Social(client))
client.add_cog(Reddit(client))
client.run(token)
