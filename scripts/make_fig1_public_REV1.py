# MAKE-FIG1-PUBLIC-REV1-2026-09-13 : Fig. 1 re-derived from the three released matrices (no workbook needed).
# Plot code, geometry, fonts and selection rule are carried verbatim from MAKE-FIG1-REV10 (the script of record,
# which reads the internal workbook week_test_book_20260829_REV3.xlsx). Only the data-loading block differs:
# the 510 (cell, source, W) values come from results/metrics/matrices/{esr,nmr,odg}_510.csv, whose MD5s are
# printed against the artifacts of record.
# Usage: python scripts/make_fig1_public_REV1.py <esr_510.csv> <nmr_510.csv> <odg_510.csv> <out.pdf>
# Fail-if-exists on outputs. Selection rule: smallest W with source-mean ESR <= -20 dB / source-mean ODG >= -0.5.
import csv,statistics as st,os,sys,hashlib
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
if len(sys.argv)!=5: sys.exit('usage: make_fig1_public_REV1.py <esr_510.csv> <nmr_510.csv> <odg_510.csv> <out.pdf>')
ESR_CSV,NMR_CSV,ODG_CSV,OUT_PDF=sys.argv[1:5]; OUT_PNG=os.path.splitext(OUT_PDF)[0]+'.png'
RECORD={'esr':'7E3AB6F1','nmr':'81BC7B78','odg':'BA4CD48F'}   # MD5 prefixes of the released matrices (MANIFEST.csv)
def md5(p): return hashlib.md5(open(p,'rb').read()).hexdigest().upper()
for tag,p in (('esr',ESR_CSV),('nmr',NMR_CSV),('odg',ODG_CSV)):
    h=md5(p); print(f'MAKE-FIG1-PUBLIC-REV1 {tag} {p} {os.path.getsize(p)} bytes MD5 {h[:8]} (record {RECORD[tag]})'
                    +('' if h.startswith(RECORD[tag]) else '  ** NOT THE ARTIFACT OF RECORD **'))
for p in (OUT_PDF,OUT_PNG):
    if os.path.exists(p): sys.exit(f"FAIL-IF-EXISTS: {p}")
cells=['rodent_max','rodent_mod','gt_max','gt_mod','fl_max','fl_mod']
names={'rodent_max':'Rodent max','rodent_mod':'Rodent mod','gt_max':'GreenTint max','gt_mod':'GreenTint mod','fl_max':'FuzzyLogic max','fl_mod':'FuzzyLogic mod'}
srcs=['gtr2','gtr4sg','prvtgtr','ytbass','nam']; W=list(range(8,25))
def load(p):
    d={}
    for r in csv.DictReader(open(p,newline='')): d[(r['cell'],r['source'],int(r['width']))]=float(r['value'])
    return d
esr,nmr,odg=load(ESR_CSV),load(NMR_CSV),load(ODG_CSV)
assert len(esr)==len(odg)==len(nmr)==510,(len(esr),len(nmr),len(odg))
sm=lambda d,c:[st.mean(d[(c,s,w)] for s in srcs) for w in W]
plt.rcParams.update({'font.size':9,'font.family':'serif','font.serif':['Times New Roman','TeX Gyre Termes','Nimbus Roman','Liberation Serif','DejaVu Serif'],'mathtext.fontset':'stix','axes.labelsize':9,'xtick.labelsize':9,'ytick.labelsize':9,'legend.fontsize':9,'axes.titlesize':9,'pdf.fonttype':42})
fig,axes=plt.subplots(2,3,figsize=(7.0,2.9))
C_ESR,C_NMR,C_ODG='#1f77b4','#2ca02c','#ff7f0e'
gaps={}
for ax,c in zip(axes.flat,cells):
    e,n,o=sm(esr,c),sm(nmr,c),sm(odg,c)
    we=next(w for w,v in zip(W,e) if v<=-20); wo=next(w for w,v in zip(W,o) if v>=-0.5); gaps[c]=wo-we
    ax.plot(W,e,'-o',color=C_ESR,ms=2.2,lw=1.0); ax.plot(W,n,'-s',color=C_NMR,ms=2.2,lw=1.0)
    ax.axhline(0,color='k',ls=':',lw=0.7)
    ax.axvspan(we,wo,color='#f2dcb3',alpha=0.55,lw=0)
    ax.axvline(we,color=C_ESR,ls='--',lw=0.9); ax.axvline(wo,color=C_ODG,ls='--',lw=0.9)
    ax2=ax.twinx(); ax2.plot(W,o,'-^',color=C_ODG,ms=2.2,lw=1.0); ax2.axhline(-0.5,color=C_ODG,ls=':',lw=0.7)
    ax2.set_ylim(-4.1,0.3); ax2.set_yticks([-4,-3,-2,-1,0])
    ax.set_xlim(7.5,24.5); ax.set_xticks([8,12,16,20,24]); ax.set_ylim(-85,32); ax.set_yticks([-80,-40,0])
    ax.set_title(f"{names[c]} (gap +{wo-we})",pad=2)
    ax.tick_params(length=2,pad=1.5); ax2.tick_params(length=2,pad=1.5)
    if ax not in axes[:,0]: ax.set_yticklabels([])
    if ax not in axes[:,2]: ax2.set_yticklabels([])
    if ax in axes[1]: ax.set_xlabel('word-length W',labelpad=1)
axes[0,0].set_ylabel('ESR / NMR (dB)',labelpad=1); axes[1,0].set_ylabel('ESR / NMR (dB)',labelpad=1)
fig.text(0.997,0.5,'PEAQ ODG',rotation=90,va='center',ha='right',fontsize=9)
from matplotlib.lines import Line2D; from matplotlib.patches import Patch
h=[Line2D([],[],color=C_ESR,marker='o',ms=3,lw=1,label='ESR (dB)'),Line2D([],[],color=C_NMR,marker='s',ms=3,lw=1,label='NMR (dB)'),Line2D([],[],color=C_ODG,marker='^',ms=3,lw=1,label='PEAQ ODG'),Patch(facecolor='#f2dcb3',label='ESR-to-ODG selection gap')]
fig.legend(handles=h,loc='upper center',ncol=4,frameon=False,bbox_to_anchor=(0.5,1.015),handlelength=1.8,columnspacing=1.2)
fig.subplots_adjust(left=0.075,right=0.945,top=0.88,bottom=0.13,wspace=0.10,hspace=0.42)
fig.savefig(OUT_PDF); fig.savefig(OUT_PNG,dpi=200)
print('MAKE-FIG1-PUBLIC-REV1 gaps',{c:f'+{g}' for c,g in gaps.items()},'(paper: +3,+4,+5,+3,+6,+4)')
for p in (OUT_PDF,OUT_PNG): print("MAKE-FIG1-PUBLIC-REV1 wrote",p,os.path.getsize(p),"bytes MD5",md5(p)[:8])
