from __future__ import annotations
import hashlib, json, os, queue, re, shutil, subprocess, sys, threading, time, urllib.parse, urllib.request, webbrowser, zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

TIME_RE=re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d+))?$")
ROW_RE=re.compile(r"^\s*\d+\s+(\d\d:\d\d:\d\d)\s+(.+?)\s*$")
KNOWN_COUNTS={'the elvenbane':25,'elvenbane':25,'elvenblood':10,'elvenborn':35}
NO_WINDOW=0x08000000 if sys.platform=='win32' else 0
AMD_ENGINE_URL='https://github.com/lemonade-sdk/whisper.cpp-rocm/releases/download/v1.8.4/whisper-v1.8.4-windows-vulkan-x64.zip'
AMD_ENGINE_SHA256='e0d20a0f92e31b98adc0faf71172efc810b701e6391a9d858ca045bff26f77cd'
AMD_MODEL_URL='https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin'
AMD_MODEL_SHA256='a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002'
AMD_MODEL_SIZE=147964211

def seconds(text):
    m=TIME_RE.match(text.strip())
    if not m: raise ValueError('Use HH:MM:SS, for example 07:42:15')
    return int(m.group(1) or 0)*3600+int(m.group(2))*60+int(m.group(3))
def clock(n):
    n=max(0,int(round(n))); return f'{n//3600:02d}:{n%3600//60:02d}:{n%60:02d}'
def esc(s): return s.replace('\\','\\\\').replace('=','\\=').replace(';','\\;').replace('#','\\#')
def duration(path):
    r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)],capture_output=True,text=True,check=True,creationflags=NO_WINDOW)
    return float(r.stdout.strip())
def sha256(path):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()
def app_data_dir():
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'AudiobookChapterMaker'
def download_verified(url,destination,expected_hash,label,progress):
    destination.parent.mkdir(parents=True,exist_ok=True); partial=destination.with_suffix(destination.suffix+'.download')
    request=urllib.request.Request(url,headers={'User-Agent':'Audiobook-Chapter-Maker'})
    with urllib.request.urlopen(request,timeout=60) as response,open(partial,'wb') as output:
        total=int(response.headers.get('Content-Length') or 0); received=0
        while True:
            block=response.read(1024*1024)
            if not block:break
            output.write(block);received+=len(block);progress(label,received,total)
    if sha256(partial).lower()!=expected_hash.lower(): partial.unlink(missing_ok=True);raise RuntimeError(label+' failed its security check. Please try again.')
    partial.replace(destination)
def ensure_amd_engine(progress):
    root=app_data_dir();engine_dir=root/'engines'/'amd-vulkan-v1.8.4';cli=engine_dir/'whisper-cli.exe';model=root/'models'/'ggml-base.en.bin';archive=root/'downloads'/'amd-vulkan-v1.8.4.zip'
    if not cli.is_file():
        if not archive.is_file() or sha256(archive).lower()!=AMD_ENGINE_SHA256: download_verified(AMD_ENGINE_URL,archive,AMD_ENGINE_SHA256,'Downloading AMD speech engine',progress)
        progress('Installing AMD speech engine',1,1)
        if engine_dir.exists(): shutil.rmtree(engine_dir)
        engine_dir.mkdir(parents=True)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target=(engine_dir/member.filename).resolve()
                if engine_dir.resolve() not in target.parents and target!=engine_dir.resolve(): raise RuntimeError('Unsafe file found in the AMD engine package.')
            bundle.extractall(engine_dir)
        archive.unlink(missing_ok=True)
    if not model.is_file() or sha256(model).lower()!=AMD_MODEL_SHA256: download_verified(AMD_MODEL_URL,model,AMD_MODEL_SHA256,'Downloading English speech model',progress)
    return cli,model
def detect_graphics_names():
    try:
        script='$n=@();try{$n+=Get-CimInstance Win32_VideoController -ErrorAction Stop|ForEach-Object Name}catch{};if(-not $n){$n+=Get-ItemProperty "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Video\\*\\0000" -ErrorAction SilentlyContinue|ForEach-Object DriverDesc};$n -join "|"'
        command=['powershell.exe','-NoLogo','-NoProfile','-Command',script]
        result=subprocess.run(command,capture_output=True,text=True,timeout=10,creationflags=NO_WINDOW)
        return result.stdout.strip()
    except Exception:return ''

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('Audiobook Maker V3'); self.geometry('780x620'); self.minsize(700,540)
        self.option_add('*Font',('Segoe UI',10)); self.q=queue.Queue(); self.chapters=[]
        self.running=False; self.cancelled=False; self.job_proc=None; self.started_at=0; self.last_percent=0
        style=ttk.Style(self); style.configure('Title.TLabel',font=('Segoe UI Semibold',18)); style.configure('Accent.TButton',font=('Segoe UI Semibold',10))
        header=ttk.Frame(self); header.pack(fill='x',padx=24,pady=(20,6))
        ttk.Label(header,text='Audiobook Maker',style='Title.TLabel').pack(side='left')
        ttk.Button(header,text='Report a Bug',command=self.report_bug).pack(side='right')
        ttk.Label(self,text='Create and repair your chaptered .m4b audiobook file. Your source files are never changed.').pack(anchor='w',padx=24)
        tabs=ttk.Notebook(self); tabs.pack(fill='both',expand=True,padx=20,pady=16)
        self.create=ttk.Frame(tabs,padding=18); self.fix=ttk.Frame(tabs,padding=18); tabs.add(self.create,text='  Create Audiobook  '); tabs.add(self.fix,text='  Fix Chapters  ')
        self.make_create(); self.make_fix(); self.protocol('WM_DELETE_WINDOW',self.on_close); self.after(150,self.poll); self.after(1000,self.tick)
        if len(sys.argv)>1: self.source.set(str(Path(sys.argv[1]).resolve()))

    def file_row(self,parent,var,label,types,command=None):
        ttk.Label(parent,text=label).pack(anchor='w'); row=ttk.Frame(parent); row.pack(fill='x',pady=(4,14)); ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='Browse…',command=command or (lambda: var.set(filedialog.askopenfilename(filetypes=types)))).pack(side='left',padx=(8,0))

    def make_create(self):
        self.source=tk.StringVar(); self.expected=tk.StringVar(value='Unknown')
        self.file_row(self.create,self.source,'Audiobook MP3',[('MP3 audiobook','*.mp3')])
        box=ttk.LabelFrame(self.create,text='Validation',padding=12); box.pack(fill='x')
        ttk.Label(box,text='Expected chapters:').grid(row=0,column=0,sticky='w'); ttk.Label(box,textvariable=self.expected).grid(row=0,column=1,sticky='w',padx=8)
        ttk.Button(box,text='Look up online',command=self.lookup).grid(row=0,column=2,padx=8); ttk.Button(box,text='Enter manually',command=self.manual_expected).grid(row=0,column=3)
        ttk.Label(box,text='The expected count guides automatic retries. Leave Unknown if unsure.',foreground='#666').grid(row=1,column=0,columnspan=4,sticky='w',pady=(8,0))
        ttk.Label(box,text='Processor:').grid(row=2,column=0,sticky='w',pady=(10,0))
        self.device_mode=tk.StringVar(value='Automatic (recommended)')
        ttk.Combobox(box,textvariable=self.device_mode,state='readonly',width=29,values=('Automatic (recommended)','Require NVIDIA GPU','Require AMD GPU','CPU only')).grid(row=2,column=1,columnspan=2,sticky='w',padx=8,pady=(10,0))
        ttk.Button(box,text='Test selected GPU',command=self.test_gpu).grid(row=2,column=3,sticky='w',pady=(10,0))
        actions=ttk.Frame(self.create); actions.pack(fill='x',pady=(18,10))
        self.start_button=ttk.Button(actions,text='Start - Create Audio Book With Chapters',style='Accent.TButton',command=self.start_create); self.start_button.pack(side='left')
        self.cancel_button=ttk.Button(actions,text='Cancel',command=self.cancel_job,state='disabled'); self.cancel_button.pack(side='left',padx=8)
        self.job_status=tk.StringVar(value='Ready'); self.time_status=tk.StringVar(value=''); self.performance_status=tk.StringVar(value='')
        ttk.Label(self.create,textvariable=self.job_status).pack(anchor='w')
        self.progress=ttk.Progressbar(self.create,mode='determinate',maximum=100); self.progress.pack(fill='x',pady=(5,3))
        ttk.Label(self.create,textvariable=self.time_status,foreground='#666').pack(anchor='w',pady=(0,8))
        ttk.Label(self.create,textvariable=self.performance_status,foreground='#555').pack(anchor='w',pady=(0,6))
        self.log=tk.Text(self.create,height=10,state='disabled',wrap='word'); self.log.pack(fill='both',expand=True)

    def make_fix(self):
        self.audio=tk.StringVar(); self.chapterfile=tk.StringVar()
        self.file_row(self.fix,self.audio,'Your .m4b file to repair',[('.m4b audiobook file','*.m4b')])
        self.file_row(self.fix,self.chapterfile,'Chapter list (*.txt)',[('Chapter list','*.txt')],self.open_chapters)
        self.tree=ttk.Treeview(self.fix,columns=('time','title'),show='headings',height=10); self.tree.heading('time',text='Start'); self.tree.heading('title',text='Chapter'); self.tree.column('time',width=110,stretch=False); self.tree.pack(fill='both',expand=True)
        row=ttk.Frame(self.fix); row.pack(fill='x',pady=10)
        ttk.Button(row,text='Add near time…',command=self.add_near).pack(side='left'); ttk.Button(row,text='Edit…',command=self.edit).pack(side='left',padx=6); ttk.Button(row,text='Delete',command=self.delete).pack(side='left'); ttk.Button(row,text='Save repaired .m4b file',style='Accent.TButton',command=self.rebuild).pack(side='right')
        self.fixstatus=tk.StringVar(value='Load your .m4b file and its chapter text file.'); ttk.Label(self.fix,textvariable=self.fixstatus,foreground='#555').pack(anchor='w')

    def write(self,s): self.q.put(('log',s))
    def poll(self):
        try:
            while True:
                kind,val=self.q.get_nowait()
                if kind=='log': self.log.configure(state='normal'); self.log.insert('end',val+'\n'); self.log.see('end'); self.log.configure(state='disabled')
                elif kind=='expected': self.expected.set(val)
                elif kind=='done': messagebox.showinfo('Finished',val)
                elif kind=='error': messagebox.showerror('Problem',val)
                elif kind=='lookup_info': messagebox.showinfo('Chapter lookup',val)
                elif kind=='gpu_info': messagebox.showinfo('GPU test',val)
                elif kind=='performance': self.performance_status.set(val)
                elif kind=='progress': self.set_progress(**val)
                elif kind=='stopped': self.finish_job(cancelled=True)
                elif kind=='job_done': self.finish_job(cancelled=False); messagebox.showinfo('Finished',val)
                elif kind=='failed': self.finish_job(error=True); messagebox.showerror('Problem',val)
        except queue.Empty: pass
        self.after(150,self.poll)

    def set_progress(self,percent=None,status=None,indeterminate=False):
        if status: self.job_status.set(status)
        if indeterminate:
            if str(self.progress['mode'])!='indeterminate': self.progress.configure(mode='indeterminate'); self.progress.start(12)
        else:
            self.progress.stop(); self.progress.configure(mode='determinate')
            if percent is not None: self.last_percent=max(0,min(100,float(percent))); self.progress['value']=self.last_percent

    def tick(self):
        if self.running:
            elapsed=max(0,time.time()-self.started_at); eta='Calculating remaining time…'
            if 1 <= self.last_percent < 100:
                remain=elapsed*(100-self.last_percent)/self.last_percent; eta='Estimated remaining: '+clock(remain)
            self.time_status.set('Elapsed: '+clock(elapsed)+'    '+eta)
        self.after(1000,self.tick)

    def finish_job(self,cancelled=False,error=False):
        self.running=False; self.job_proc=None; self.progress.stop(); self.progress.configure(mode='determinate'); self.start_button.configure(state='normal'); self.cancel_button.configure(state='disabled')
        if cancelled: self.job_status.set('Cancelled'); self.time_status.set('The original audiobook was not changed.')
        elif error: self.progress['value']=0; self.last_percent=0; self.job_status.set('Stopped because of a problem')
        else: self.progress['value']=100; self.last_percent=100; self.job_status.set('Finished')

    def cancel_job(self):
        if not self.running or not messagebox.askyesno('Cancel processing','Stop the current audiobook job?\n\nThe original MP3 will remain unchanged.'): return
        self.cancelled=True; self.job_status.set('Cancelling…'); proc=self.job_proc
        if proc and proc.poll() is None:
            try:
                if sys.platform=='win32': subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,creationflags=NO_WINDOW)
                else: proc.terminate()
            except Exception: pass

    def on_close(self):
        if self.running:
            if not messagebox.askyesno('Processing is still running','Closing now will cancel the current job.\n\nClose Audiobook Maker?'): return
            self.cancelled=True; proc=self.job_proc
            if proc and proc.poll() is None:
                try:
                    if sys.platform=='win32': subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,creationflags=NO_WINDOW)
                    else: proc.terminate()
                except Exception: pass
        self.destroy()

    def manual_expected(self):
        n=simpledialog.askinteger('Expected chapters','How many numbered chapters should the book contain?',minvalue=1,maxvalue=999)
        if n: self.expected.set(str(n))

    def report_bug(self):
        webbrowser.open('https://github.com/shadman48/audiobook-chapter-maker/issues/new?template=bug_report.yml')


    def test_gpu(self):
        if self.running: return messagebox.showinfo('NVIDIA GPU test','Wait for the current audiobook job to finish or cancel it first.')
        if self.device_mode.get()=='Require AMD GPU' or ('amd' in detect_graphics_names().lower() or 'radeon' in detect_graphics_names().lower()): return self.test_amd_gpu()
        self.job_status.set('Testing NVIDIA GPU…')
        def work():
            try:
                import ctranslate2, numpy as np
                from faster_whisper import WhisperModel
                count=ctranslate2.get_cuda_device_count()
                if count < 1: raise RuntimeError('No CUDA-capable NVIDIA GPU was detected.')
                model=WhisperModel('base.en',device='cuda',compute_type='float16')
                segments,_=model.transcribe(np.zeros(16000,dtype=np.float32),language='en'); list(segments)
                self.q.put(('gpu_info',f'GPU test passed. Whisper can use {count} NVIDIA CUDA device(s).'))
                self.q.put(('progress',{'percent':0,'status':'NVIDIA GPU ready'}))
            except Exception as e:
                self.q.put(('gpu_info','GPU acceleration is not ready, so Automatic mode will use the CPU.\n\n'+str(e)+'\n\nFaster-whisper currently requires an NVIDIA CUDA GPU, CUDA 12 cuBLAS, and cuDNN 9.'))
                self.q.put(('progress',{'percent':0,'status':'GPU unavailable — CPU fallback available'}))
        threading.Thread(target=work,daemon=True).start()

    def test_amd_gpu(self):
        self.job_status.set('Testing AMD Vulkan GPU…')
        def work():
            try:
                import tempfile
                def progress(label,done,total): self.q.put(('progress',{'percent':100*done/max(1,total),'status':label+'…'}))
                cli,model=ensure_amd_engine(progress)
                with tempfile.TemporaryDirectory() as d:
                    wav=Path(d)/'silence.wav'
                    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','anullsrc=r=16000:cl=mono','-t','1','-y',str(wav)],check=True,creationflags=NO_WINDOW)
                    result=subprocess.run([str(cli),'-m',str(model),'-f',str(wav),'-l','en'],capture_output=True,text=True,creationflags=NO_WINDOW,timeout=120)
                details=(result.stdout+'\n'+result.stderr)
                if result.returncode: raise RuntimeError(details[-1200:])
                if not re.search(r'vulkan|ggml_vulkan',details,re.I): raise RuntimeError('The executable ran, but did not report a Vulkan backend. Choose a Vulkan-enabled whisper.cpp build.')
                self.q.put(('gpu_info','AMD GPU test passed. whisper.cpp reported an active Vulkan backend.'))
                self.q.put(('progress',{'percent':0,'status':'AMD Vulkan GPU ready'}))
            except Exception as e:
                self.q.put(('gpu_info','AMD Vulkan acceleration is not ready.\n\n'+str(e)))
                self.q.put(('progress',{'percent':0,'status':'AMD GPU setup required'}))
        threading.Thread(target=work,daemon=True).start()
    def lookup(self):
        p=Path(self.source.get()); title=re.sub(r'\[[^]]+\]',' ',p.stem); title=re.sub(r'\b(Mercedes Lackey|Andre Norton)\b',' ',title,flags=re.I); title=' '.join(title.split())
        normalized=' '.join(re.sub(r'[^a-z0-9 ]',' ',title.lower()).split())
        local=next(((name,count) for name,count in KNOWN_COUNTS.items() if name in normalized),None)
        if local:
            self.expected.set(f'{local[1]} — {title} (verified reference)')
            return
        def work():
            try:
                url='https://www.googleapis.com/books/v1/volumes?q='+urllib.parse.quote('intitle:'+title)+'&maxResults=5'
                data=json.load(urllib.request.urlopen(url,timeout=12)); best=(data.get('items') or [])[0]['volumeInfo']; preview=best.get('previewLink')
                if not preview: raise ValueError('No table of contents was available.')
                html=urllib.request.urlopen(preview,timeout=12).read().decode('utf-8','ignore'); nums=[int(x) for x in re.findall(r'Chapter\s+(\d{1,3})',html,re.I)]
                if not nums: raise ValueError('The book was found, but its chapter count was not published.')
                self.q.put(('expected',f'{max(nums)} — {best.get("title",title)}'))
            except Exception as e:
                detail='The online book service is temporarily busy.' if '429' in str(e) else 'No published chapter count was found.'
                self.q.put(('lookup_info',detail+' You can enter the expected count manually; audiobook creation is unaffected.'))
        threading.Thread(target=work,daemon=True).start()

    def start_create(self):
        p=Path(self.source.get())
        if not p.is_file(): return messagebox.showerror('Choose a file','Please choose an audiobook MP3.')
        if not re.match(r'(\d+)',self.expected.get()):
            normalized=' '.join(re.sub(r'[^a-z0-9 ]',' ',p.stem.lower()).split())
            local=next(((name,count) for name,count in KNOWN_COUNTS.items() if name in normalized),None)
            if local: self.expected.set(f'{local[1]} — {p.stem} (verified reference)')
        try: book_seconds=duration(p)
        except Exception as e: return messagebox.showerror('Cannot read audiobook','The audiobook duration could not be read.\n\n'+str(e))
        hours=book_seconds/3600
        warning=f'This audiobook is {hours:.1f} hours long.\n\nLarge books can take a long time to process. Keep your computer plugged in and prevent it from sleeping.\n\nStart now?'
        if not messagebox.askokcancel('Before you start',warning): return
        self.running=True; self.cancelled=False; self.started_at=time.time(); self.last_percent=0
        self.performance_status.set('')
        self.start_button.configure(state='disabled'); self.cancel_button.configure(state='normal'); self.set_progress(status='Starting…',indeterminate=True)
        self.write('Starting faster chapter scan…')
        def work():
            try:
                script=Path(__file__).with_name('detect_chapters_v2.py')
                if not script.is_file():
                    raise FileNotFoundError('The V3 engine file detect_chapters_v2.py is missing. Extract every file from the V3 ZIP into the same folder.')
                command=[sys.executable,'-u',str(script),str(p)]
                expected_match=re.match(r'(\d+)',self.expected.get())
                if expected_match: command += ['--expected',expected_match.group(1)]
                selected=self.device_mode.get();graphics=detect_graphics_names().lower()
                device={'Automatic (recommended)':('amd' if ('amd' in graphics or 'radeon' in graphics) else 'auto'),'Require NVIDIA GPU':'cuda','Require AMD GPU':'amd','CPU only':'cpu'}[selected]
                command += ['--device',device]
                if device=='amd':
                    def setup_progress(label,done,total): self.q.put(('progress',{'percent':100*done/max(1,total),'status':label+'…'}))
                    cli,model=ensure_amd_engine(setup_progress)
                    command += ['--amd-cli',str(cli),'--amd-model',str(model)]
                proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,creationflags=NO_WINDOW)
                self.job_proc=proc
                for line in proc.stdout:
                    line=line.rstrip(); self.write(line)
                    if line.startswith('Step 1/3:'): self.q.put(('progress',{'status':'Finding likely chapter breaks…','indeterminate':True}))
                    elif line.startswith('Step 2/3:'): self.q.put(('progress',{'percent':10,'status':'Listening near likely chapter breaks…'}))
                    elif line.startswith('ACTIVE PROCESSOR:'): self.q.put(('progress',{'percent':10,'status':'Using '+line.split(':',1)[1].strip()}))
                    elif line.strip().startswith('AMD tuning:'): self.q.put(('performance',line.strip()))
                    elif line.strip().startswith('Transcription speed:'): self.q.put(('performance',line.strip()))
                    elif line.startswith('Thorough fallback:'): self.q.put(('progress',{'status':'Running a thorough full-book scan…','indeterminate':True}))
                    elif line.startswith('Thorough scan:'): self.q.put(('progress',{'status':'Scanning the full book with AMD Vulkan…','indeterminate':True}))
                    elif line.startswith('Context analysis:'): self.q.put(('progress',{'status':'Checking pauses and surrounding context…','indeterminate':True}))
                    elif line.strip().startswith('Progress:'):
                        m=re.search(r'(\d+)/(\d+)',line)
                        if m:
                            label='Processing audiobook section' if 'audiobook sections' in line else 'Checking location'
                            self.q.put(('progress',{'percent':10+70*int(m.group(1))/max(1,int(m.group(2))),'status':f'{label} {m.group(1)} of {m.group(2)}…'}))
                    elif line.startswith('Step 3/3:'): self.q.put(('progress',{'percent':82,'status':'Creating your .m4b file…'}))
                    elif line.startswith('out_time='):
                        try: self.q.put(('progress',{'percent':82+18*seconds(line.split('=',1)[1])/book_seconds,'status':'Creating your .m4b file…'}))
                        except ValueError: pass
                code=proc.wait()
                if self.cancelled:
                    for partial in p.parent.glob(p.stem+'*.working.m4b'):
                        try: partial.unlink()
                        except OSError: pass
                    self.q.put(('stopped','')); return
                if code: raise RuntimeError('Creation did not finish successfully. See the log.')
                chapter_path=p.with_name(p.stem+' - chapters.txt')
                detected=[]
                if chapter_path.exists():
                    detected=[int(x) for x in re.findall(r'Chapter\s+(\d+)',chapter_path.read_text(encoding='utf-8-sig'),re.I)]
                expected_match=re.match(r'(\d+)',self.expected.get())
                if expected_match and detected:
                    wanted=int(expected_match.group(1)); present=set(detected); missing=[n for n in range(1,wanted+1) if n not in present]
                    self.write(f'Validation: detected {len(present)} of {wanted} expected numbered chapters.')
                    self.write('Missing: '+(', '.join('Chapter '+str(n) for n in missing) if missing else 'none — MATCH'))
                self.q.put(('job_done','Your .m4b file and chapter list were saved beside the MP3.'))
            except Exception as e: self.q.put(('failed',str(e)))
        threading.Thread(target=work,daemon=True).start()

    def open_chapters(self):
        f=filedialog.askopenfilename(filetypes=[('Chapter list','*.txt')]);
        if not f: return
        self.chapterfile.set(f); self.chapters=[]
        for line in Path(f).read_text(encoding='utf-8-sig').splitlines():
            m=ROW_RE.match(line)
            if m: self.chapters.append([seconds(m.group(1)),m.group(2)])
        self.refresh(); self.fixstatus.set(f'Loaded {len(self.chapters)} chapter markers.')
    def refresh(self):
        self.chapters.sort(key=lambda x:x[0]); self.tree.delete(*self.tree.get_children())
        for i,(t,n) in enumerate(self.chapters): self.tree.insert('', 'end', iid=str(i), values=(clock(t),n))
    def add_near(self):
        title=simpledialog.askstring('Add chapter','Chapter name (for example, Chapter 7):');
        if not title:return
        approx=simpledialog.askstring('Approximate time','Approximate HH:MM:SS:');
        if not approx:return
        try: point=seconds(approx)
        except ValueError as e:return messagebox.showerror('Invalid time',str(e))
        audio=Path(self.audio.get())
        if not audio.is_file(): return messagebox.showerror('Choose your .m4b file','Choose your existing .m4b file first.')
        self.fixstatus.set('Listening around that time for the spoken heading…')
        def work():
            try:
                from faster_whisper import WhisperModel
                start=max(0,point-30); model=WhisperModel('base.en',device='cpu',compute_type='int8')
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    clip=Path(d)/'clip.wav'; subprocess.run(['ffmpeg','-v','error','-y','-ss',str(start),'-i',str(audio),'-t','60','-ac','1','-ar','16000',str(clip)],check=True,creationflags=NO_WINDOW)
                    segs,_=model.transcribe(str(clip),language='en',word_timestamps=True,vad_filter=True)
                    best=None
                    for seg in segs:
                        if re.search(re.escape(title),seg.text,re.I): best=start+seg.start; break
                stamp=best if best is not None else point
                self.after(0,lambda:self.confirm_add(stamp,title,best is not None))
            except Exception as e:self.q.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()
    def confirm_add(self,t,title,found):
        msg=(f'Spoken heading found near {clock(t)}.' if found else f'Whisper did not find it. Use your approximate time {clock(t)}?')
        if messagebox.askyesno('Confirm chapter',msg+'\n\nAdd '+title+'?'): self.chapters.append([t,title]); self.refresh(); self.fixstatus.set('Chapter added. Save your repaired .m4b file when ready.')
    def edit(self):
        sel=self.tree.selection();
        if not sel:return
        i=int(sel[0]); old=self.chapters[i]; name=simpledialog.askstring('Edit chapter','Chapter name:',initialvalue=old[1]); tm=simpledialog.askstring('Edit chapter','Start time:',initialvalue=clock(old[0]))
        if name and tm:
            try:self.chapters[i]=[seconds(tm),name];self.refresh()
            except ValueError as e:messagebox.showerror('Invalid time',str(e))
    def delete(self):
        sel=self.tree.selection();
        if sel and messagebox.askyesno('Delete chapter','Remove the selected chapter marker?'): self.chapters.pop(int(sel[0]));self.refresh()
    def rebuild(self):
        audio=Path(self.audio.get())
        if not audio.is_file() or not self.chapters:return messagebox.showerror('Missing information','Load your .m4b file and chapter list first.')
        try:
            total=duration(audio); meta=audio.with_name(audio.stem+' - repaired.ffmetadata'); out=audio.with_name(audio.stem+' - repaired.m4b'); txt=audio.with_name(audio.stem+' - repaired chapters.txt')
            lines=[';FFMETADATA1']
            for i,(t,n) in enumerate(self.chapters): lines += ['[CHAPTER]','TIMEBASE=1/1000',f'START={int(t*1000)}',f'END={int((self.chapters[i+1][0] if i+1<len(self.chapters) else total)*1000)}',f'title={esc(n)}']
            meta.write_text('\n'.join(lines)+'\n',encoding='utf-8'); txt.write_text('\n'.join(f'{i:02d}  {clock(t)}  {n}' for i,(t,n) in enumerate(self.chapters,1))+'\n',encoding='utf-8')
            subprocess.run(['ffmpeg','-hide_banner','-y','-i',str(audio),'-i',str(meta),'-map','0:a:0','-map_metadata','1','-map_chapters','1','-c','copy',str(out)],check=True,creationflags=NO_WINDOW)
            messagebox.showinfo('Repair complete',f'Saved without re-encoding:\n{out}')
        except Exception as e:messagebox.showerror('Repair failed',str(e))

if __name__=='__main__': App().mainloop()
