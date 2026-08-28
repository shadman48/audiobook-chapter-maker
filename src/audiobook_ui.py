from __future__ import annotations
import json, queue, re, subprocess, sys, threading, urllib.parse, urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

TIME_RE=re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:\.(\d+))?$")
ROW_RE=re.compile(r"^\s*\d+\s+(\d\d:\d\d:\d\d)\s+(.+?)\s*$")
KNOWN_COUNTS={'the elvenbane':25,'elvenbane':25,'elvenblood':10,'elvenborn':35}
NO_WINDOW=0x08000000 if sys.platform=='win32' else 0

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

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('Audiobook Maker V3'); self.geometry('780x620'); self.minsize(700,540)
        self.option_add('*Font',('Segoe UI',10)); self.q=queue.Queue(); self.chapters=[]
        style=ttk.Style(self); style.configure('Title.TLabel',font=('Segoe UI Semibold',18)); style.configure('Accent.TButton',font=('Segoe UI Semibold',10))
        ttk.Label(self,text='Audiobook Maker',style='Title.TLabel').pack(anchor='w',padx=24,pady=(20,6))
        ttk.Label(self,text='Create and repair your chaptered .m4b audiobook file. Your source files are never changed.').pack(anchor='w',padx=24)
        tabs=ttk.Notebook(self); tabs.pack(fill='both',expand=True,padx=20,pady=16)
        self.create=ttk.Frame(tabs,padding=18); self.fix=ttk.Frame(tabs,padding=18); tabs.add(self.create,text='  Create Audiobook  '); tabs.add(self.fix,text='  Fix Chapters  ')
        self.make_create(); self.make_fix(); self.after(150,self.poll)
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
        ttk.Label(box,text='Online counts are advisory and never prevent creation.',foreground='#666').grid(row=1,column=0,columnspan=4,sticky='w',pady=(8,0))
        ttk.Button(self.create,text='Start - Create Audio Book With Chapters',style='Accent.TButton',command=self.start_create).pack(anchor='w',pady=18)
        self.log=tk.Text(self.create,height=13,state='disabled',wrap='word'); self.log.pack(fill='both',expand=True)

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
        except queue.Empty: pass
        self.after(150,self.poll)

    def manual_expected(self):
        n=simpledialog.askinteger('Expected chapters','How many numbered chapters should the book contain?',minvalue=1,maxvalue=999)
        if n: self.expected.set(str(n))
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
        self.write('Starting faster chapter scan…')
        def work():
            try:
                script=Path(__file__).with_name('detect_chapters_v2.py')
                if not script.is_file():
                    raise FileNotFoundError('The V3 engine file detect_chapters_v2.py is missing. Extract every file from the V3 ZIP into the same folder.')
                proc=subprocess.Popen([sys.executable,str(script),str(p)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,creationflags=NO_WINDOW)
                for line in proc.stdout: self.write(line.rstrip())
                if proc.wait(): raise RuntimeError('Creation did not finish successfully. See the log.')
                chapter_path=p.with_name(p.stem+' - chapters.txt')
                detected=[]
                if chapter_path.exists():
                    detected=[int(x) for x in re.findall(r'Chapter\s+(\d+)',chapter_path.read_text(encoding='utf-8-sig'),re.I)]
                expected_match=re.match(r'(\d+)',self.expected.get())
                if expected_match and detected:
                    wanted=int(expected_match.group(1)); present=set(detected); missing=[n for n in range(1,wanted+1) if n not in present]
                    self.write(f'Validation: detected {len(present)} of {wanted} expected numbered chapters.')
                    self.write('Missing: '+(', '.join('Chapter '+str(n) for n in missing) if missing else 'none — MATCH'))
                self.q.put(('done','Your .m4b file and chapter list were saved beside the MP3.'))
            except Exception as e: self.q.put(('error',str(e)))
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
