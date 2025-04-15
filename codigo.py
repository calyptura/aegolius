import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import datetime
import requests
from io import StringIO
import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict
import folium
from streamlit_folium import st_folium
from streamlit_carousel import carousel

# Configuração da página
st.set_page_config(
    page_title="Passarinhômetro - Avistar 2025",
    page_icon="🦉",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Constantes para benchmarks (você pode ajustar conforme necessário)
TOTAL_ESPECIES_POTENCIAL = 300  # Número potencial de espécies na região
TOTAL_LISTAS_META = 100  # Meta de listas para o período
TOTAL_PASSARINHANTES_META = 50  # Meta de observadores para o período


# Função para carregar dados do Google Sheets
@st.cache_data(ttl=600)  # Cache por 10 minutos
def load_google_sheet_data(sheet_url):
    try:
        # Extrai o ID da planilha
        sheet_id = sheet_url.split('/d/')[1].split('/edit')[0]

        # Abas que queremos carregar
        sheet_names = [
            "checklists_compilados",  # Nova aba com os dados compilados
            "checklists_L2015671",
            "observations_L2015671",
            "species_list_L2015671",
            "checklist_feed_L2015671_2025-01"
        ]

        sheet_data = {}

        for sheet_name in sheet_names:
            try:
                # Constrói a URL de exportação da aba específica
                export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

                # Faz a requisição HTTP
                response = requests.get(export_url)

                # Verifica se a requisição foi bem-sucedida
                if response.status_code == 200:
                    # Lê o conteúdo como CSV
                    csv_content = StringIO(response.content.decode('utf-8'))
                    df = pd.read_csv(csv_content, low_memory=False)

                    if not df.empty:
                        sheet_data[sheet_name] = df
            except Exception as e:
                pass  # Silenciosamente ignora erros de carregamento de abas

        return sheet_data

    except Exception as e:
        st.error(f"Erro ao carregar dados: {e}")
        return {}


# Função para criar gráfico gauge circular
def create_gauge_chart(value, max_value, title, color):
    percentage = min(100, int((value / max_value * 100) if max_value > 0 else 0))

    # Criar o indicador gauge com título melhorado
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=percentage,
        domain={'x': [0, 1], 'y': [0, 1]},
        number={'suffix': "%"},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "darkblue"},
            'bar': {'color': color},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [0, 100], 'color': 'lightgray'}
            ],
        },
        # Removido o título do indicador
    ))

    # Adicionando o título como uma anotação para melhor visibilidade
    fig.update_layout(
        height=200,
        margin=dict(l=30, r=30, t=50, b=30),
        # Adiciona um título à figura em vez de ao indicador
        title={
            'text': f"<b>{title}</b><br><span style='font-size:0.8em;'>{value}/{max_value}</span>",
            'y': 0.95,  # Posição vertical do título
            'x': 0.5,   # Posição horizontal do título (centralizado)
            'xanchor': 'center',
            'yanchor': 'top',
            'font': {'size': 16}
        }
    )

    return fig


# Função para filtrar dados para um período específico
def filter_data_by_date(df, start_date, end_date, date_column='obsDt'):
    """Filtra dataframe para um período específico, lidando com diferentes formatos de data"""
    if df.empty or date_column not in df.columns:
        return pd.DataFrame()

    # Copia o dataframe para não modificar o original
    filtered_df = df.copy()

    # Detecta o formato da data e converte para datetime
    # Verifica se a coluna é do tipo string
    if pd.api.types.is_string_dtype(filtered_df[date_column]):
        # Tenta diferentes formatos de data
        try:
            # Formato: "2025-04-13 14:2" conforme visto na nova estrutura
            filtered_df[date_column] = pd.to_datetime(filtered_df[date_column], errors='coerce')
        except:
            st.warning(f"Não foi possível converter a coluna de data: {date_column}")
            return pd.DataFrame()

    # Filtra para o período especificado
    mask = (filtered_df[date_column] >= pd.to_datetime(start_date)) & (
            filtered_df[date_column] <= pd.to_datetime(end_date))
    return filtered_df[mask].copy()


# Função para obter estatísticas de espécies, listas e observadores
def get_event_stats(sheets_data, start_date, end_date):
    """Obtém estatísticas de espécies, listas e observadores para o período selecionado"""
    stats = {
        'especies': 0,
        'listas': 0,
        'observadores': 0
    }

    # Conjuntos para rastrear elementos únicos
    unique_species = set()
    unique_checklists = set()
    unique_observers = set()

    # Primeiro verificamos se temos a aba checklists_compilados
    if 'checklists_compilados' in sheets_data:
        obs_df = sheets_data['checklists_compilados']

        # Converter formato de data
        if 'obsDt' in obs_df.columns and pd.api.types.is_string_dtype(obs_df['obsDt']):
            try:
                # Formato na nova estrutura: "2025-04-13 14:2"
                obs_df['obsDt'] = pd.to_datetime(obs_df['obsDt'], errors='coerce')
            except:
                st.warning("Não foi possível converter datas para análise de estatísticas")

        # Filtrar para o período selecionado
        filtered_df = obs_df.copy()
        if 'obsDt' in filtered_df.columns and pd.api.types.is_datetime64_dtype(filtered_df['obsDt']):
            mask = (filtered_df['obsDt'] >= pd.to_datetime(start_date)) & (
                    filtered_df['obsDt'] <= pd.to_datetime(end_date))
            filtered_df = filtered_df[mask]

        # Adicionar espécies únicas (usando commonName se não tiver speciesCode)
        if 'speciesCode' in filtered_df.columns:
            unique_species.update(filtered_df['speciesCode'].unique())
        elif 'commonName' in filtered_df.columns:  # Usar commonName como alternativa
            unique_species.update(filtered_df['commonName'].unique())

        # Adicionar observadores únicos
        if 'userDisplayName' in filtered_df.columns:
            unique_observers.update(filtered_df['userDisplayName'].unique())

        # Adicionar listas únicas
        if 'subId' in filtered_df.columns:
            unique_checklists.update(filtered_df['subId'].unique())

    # Se não tiver checklists_compilados, tentamos usar as abas tradicionais
    elif 'observations_L2015671' in sheets_data:
        obs_df = sheets_data['observations_L2015671']

        # Converter formato de data
        if 'obsDt' in obs_df.columns and pd.api.types.is_string_dtype(obs_df['obsDt']):
            try:
                obs_df['obsDt'] = pd.to_datetime(obs_df['obsDt'], errors='coerce')
            except:
                st.warning("Não foi possível converter datas para análise de estatísticas")

        # Filtrar para o período selecionado
        filtered_df = obs_df.copy()
        if 'obsDt' in filtered_df.columns and pd.api.types.is_datetime64_dtype(filtered_df['obsDt']):
            mask = (filtered_df['obsDt'] >= pd.to_datetime(start_date)) & (
                    filtered_df['obsDt'] <= pd.to_datetime(end_date))
            filtered_df = filtered_df[mask]

        # Adicionar espécies únicas
        if 'speciesCode' in filtered_df.columns:
            unique_species.update(filtered_df['speciesCode'].unique())

        # Adicionar observadores únicos
        if 'userDisplayName' in filtered_df.columns:
            unique_observers.update(filtered_df['userDisplayName'].unique())

        # Adicionar listas únicas
        if 'subId' in filtered_df.columns:
            unique_checklists.update(filtered_df['subId'].unique())

    # Extrair dados da aba de checklists (para complementar)
    if 'checklists_L2015671' in sheets_data and 'checklists_compilados' not in sheets_data:
        checklist_df = sheets_data['checklists_L2015671']

        # Converter formato de data
        if 'obsDt' in checklist_df.columns and pd.api.types.is_string_dtype(checklist_df['obsDt']):
            try:
                # Formato flexível
                checklist_df['obsDt'] = pd.to_datetime(checklist_df['obsDt'], errors='coerce')
            except:
                st.warning("Não foi possível converter datas na aba de checklists")

        # Filtrar para o período selecionado
        filtered_checklists = checklist_df.copy()
        if 'obsDt' in filtered_checklists.columns and pd.api.types.is_datetime64_dtype(filtered_checklists['obsDt']):
            mask = (filtered_checklists['obsDt'] >= pd.to_datetime(start_date)) & (
                    filtered_checklists['obsDt'] <= pd.to_datetime(end_date))
            filtered_checklists = filtered_checklists[mask]

        # Adicionar listas únicas
        if 'subId' in filtered_checklists.columns:
            unique_checklists.update(filtered_checklists['subId'].unique())

        # Adicionar observadores únicos (caso não estejam na aba de observações)
        if 'userDisplayName' in filtered_checklists.columns:
            unique_observers.update(filtered_checklists['userDisplayName'].unique())

    # Preencher estatísticas
    stats['especies'] = len(unique_species)
    stats['listas'] = len(unique_checklists)
    stats['observadores'] = len(unique_observers)

    return stats


# Função para obter as últimas espécies observadas
# Função para obter as últimas espécies observadas
def get_latest_species(sheets_data, start_date, end_date, limit=100):
    """Obtém as últimas espécies observadas no período selecionado"""
    # Primeiro verificamos se temos a aba checklists_compilados
    if 'checklists_compilados' in sheets_data:
        df = sheets_data['checklists_compilados']
    elif 'observations_L2015671' in sheets_data:
        df = sheets_data['observations_L2015671']
    else:
        return pd.DataFrame()

    # Verifica se temos a coluna de data e espécie
    if 'obsDt' not in df.columns:
        st.warning(f"Coluna obsDt ausente na aba")
        return pd.DataFrame()

    # Verifica qual coluna usar para a espécie (speciesCode ou commonName)
    species_col = 'commonName' if 'commonName' in df.columns else 'speciesCode' if 'speciesCode' in df.columns else None
    if not species_col:
        st.warning("Não foi encontrada coluna para identificação de espécies")
        return pd.DataFrame()

    # Converte a coluna de data para datetime
    if pd.api.types.is_string_dtype(df['obsDt']):
        try:
            df['obsDt'] = pd.to_datetime(df['obsDt'], errors='coerce')
        except:
            st.warning("Não foi possível converter a coluna de data para datetime")
            return pd.DataFrame()

    # Filtra para o período selecionado
    filtered_df = filter_data_by_date(df, start_date, end_date)

    if filtered_df.empty:
        return pd.DataFrame()

    # Ordena por data (mais recente primeiro) e pega os primeiros registros
    df_sorted = filtered_df.sort_values('obsDt', ascending=False)
    latest = df_sorted.head(limit)

    # Seleciona apenas as colunas necessárias
    cols_to_select = ['obsDt', species_col]

    # Adiciona userDisplayName se disponível (mas não adiciona subId)
    if 'userDisplayName' in latest.columns:
        cols_to_select.append('userDisplayName')

    result = latest[cols_to_select].copy()

    # Renomeia a coluna para padronizar
    if species_col != 'commonName':
        result = result.rename(columns={species_col: 'commonName'})

    return result


# Função para obter as últimas listas
def get_latest_checklists(sheets_data, start_date, end_date, limit=100):
    """Obtém as últimas listas submetidas no período selecionado"""
    # Primeiro verificamos se temos a aba checklists_compilados
    if 'checklists_compilados' in sheets_data:
        df = sheets_data['checklists_compilados']
    elif 'observations_L2015671' in sheets_data:
        # Tentar usar a aba de observações
        df = sheets_data['observations_L2015671']
    elif 'checklist_feed_L2015671_2025-01' in sheets_data:
        # Tentar usar a aba de checklist_feed como alternativa
        df = sheets_data['checklist_feed_L2015671_2025-01']
    else:
        return pd.DataFrame()

    # Verifica se temos as colunas necessárias
    if 'obsDt' not in df.columns or 'subId' not in df.columns:
        st.warning("Colunas obsDt e/ou subId ausentes")
        return pd.DataFrame()

    # Converte a coluna de data para datetime
    if pd.api.types.is_string_dtype(df['obsDt']):
        try:
            df['obsDt'] = pd.to_datetime(df['obsDt'], errors='coerce')
        except:
            st.warning("Não foi possível converter a coluna de data para datetime")
            return pd.DataFrame()

    # Filtra para o período selecionado
    if pd.api.types.is_datetime64_dtype(df['obsDt']):
        mask = (df['obsDt'] >= pd.to_datetime(start_date)) & (df['obsDt'] <= pd.to_datetime(end_date))
        filtered_df = df[mask].copy()
    else:
        filtered_df = df.copy()
        st.warning("Filtragem por data não aplicada - formato de data inválido")

    # Verifica se há dados após a filtragem
    if filtered_df.empty:
        return pd.DataFrame()

    # Se userDisplayName não está disponível, use um valor padrão
    if 'userDisplayName' not in filtered_df.columns:
        filtered_df['userDisplayName'] = "Observador"

    # Agrupa por subId para obter checklists únicos
    checklists = filtered_df.groupby(['subId', 'obsDt', 'userDisplayName']).size().reset_index(name='num_especies')

    # Ordena por data (mais recente primeiro)
    checklists_sorted = checklists.sort_values('obsDt', ascending=False)

    # Pega os primeiros registros
    latest = checklists_sorted.head(limit)

    return latest


# Função para obter top espécies
def get_top_species(sheets_data, start_date, end_date, limit=10):
    """Obtém as espécies mais observadas no período"""
    # Primeiro verificamos se temos a aba checklists_compilados
    if 'checklists_compilados' in sheets_data:
        df = sheets_data['checklists_compilados']
    elif 'observations_L2015671' in sheets_data:
        df = sheets_data['observations_L2015671']
    else:
        return pd.DataFrame()

    # Verifica se temos a coluna de data
    if 'obsDt' not in df.columns:
        st.warning("Coluna obsDt ausente")
        return pd.DataFrame()

    # Verifica qual coluna usar para a espécie (commonName ou speciesCode)
    species_col = 'commonName' if 'commonName' in df.columns else 'speciesCode' if 'speciesCode' in df.columns else None
    if not species_col:
        st.warning("Não foi encontrada coluna para identificação de espécies")
        return pd.DataFrame()

    # Filtra para o período selecionado
    filtered_df = filter_data_by_date(df, start_date, end_date)

    if filtered_df.empty:
        return pd.DataFrame()

    # Conta ocorrências por espécie
    species_counts = filtered_df[species_col].value_counts().reset_index()
    species_counts.columns = ['Espécie', 'Contagem']

    # Pega as top espécies
    top_species = species_counts.head(limit)

    return top_species


# Função para obter top observadores
def get_top_observers(sheets_data, start_date, end_date, limit=10):
    """Obtém os observadores mais ativos no período"""
    # Primeiro verificamos se temos a aba checklists_compilados
    if 'checklists_compilados' in sheets_data:
        df = sheets_data['checklists_compilados']
    elif 'observations_L2015671' in sheets_data:
        df = sheets_data['observations_L2015671']
    else:
        return pd.DataFrame()

    # Verifica se temos as colunas necessárias
    if 'obsDt' not in df.columns or 'userDisplayName' not in df.columns:
        st.warning(f"Colunas ausentes para calcular top observadores")
        return pd.DataFrame()

    # Filtra para o período selecionado
    filtered_df = filter_data_by_date(df, start_date, end_date)

    if filtered_df.empty:
        return pd.DataFrame()

    # Verifica qual coluna usar para contar espécies únicas
    if 'speciesCode' in filtered_df.columns:
        count_column = 'speciesCode'
    elif 'commonName' in filtered_df.columns:
        count_column = 'commonName'
    else:
        # Se não houver coluna de espécie, contamos observações (entradas na tabela)
        observer_counts = filtered_df['userDisplayName'].value_counts().reset_index()
        observer_counts.columns = ['Observador', 'Contagem']
        return observer_counts.sort_values('Contagem', ascending=False).head(limit)

    # Para observações, contamos espécies únicas por observador
    observer_counts = filtered_df.groupby('userDisplayName')[count_column].nunique().reset_index()
    observer_counts.columns = ['Observador', 'Contagem']

    # Pega os top observadores
    top_observers = observer_counts.sort_values('Contagem', ascending=False).head(limit)

    return top_observers

# Função para obter top observadores por listas
def get_top_observers_by_lists(sheets_data, start_date, end_date, limit=10):
    """Obtém os observadores que submeteram mais listas no período"""
    # Primeiro verificamos se temos a aba checklists_compilados
    if 'checklists_compilados' in sheets_data:
        df = sheets_data['checklists_compilados']
    elif 'checklists_L2015671' in sheets_data:
        df = sheets_data['checklists_L2015671']
    else:
        return pd.DataFrame()

    # Verifica se temos as colunas necessárias
    if 'obsDt' not in df.columns or 'userDisplayName' not in df.columns or 'subId' not in df.columns:
        st.warning(f"Colunas ausentes para calcular top observadores por listas")
        return pd.DataFrame()

    # Filtra para o período selecionado
    filtered_df = filter_data_by_date(df, start_date, end_date)

    if filtered_df.empty:
        return pd.DataFrame()

    # Contagem de listas únicas por observador
    # Agrupa por observador e subId para contar listas únicas
    observer_lists = filtered_df.groupby(['userDisplayName', 'subId']).size().reset_index(name='temp')
    observer_counts = observer_lists.groupby('userDisplayName').size().reset_index(name='Contagem')

    # Pega os top observadores por número de listas
    top_observers = observer_counts.sort_values('Contagem', ascending=False).head(limit)
    top_observers.columns = ['Observador', 'Contagem']

    return top_observers


# Função para obter dados de tendência por dia
def get_daily_trend(sheets_data, start_date, end_date):
    """Obtém dados de tendência diária de espécies e observações"""
    # Primeiro verificamos se temos a aba checklists_compilados
    if 'checklists_compilados' in sheets_data:
        df = sheets_data['checklists_compilados']
    elif 'observations_L2015671' in sheets_data:
        df = sheets_data['observations_L2015671']
    else:
        return pd.DataFrame()

    # Verifica se temos a coluna de data
    if 'obsDt' not in df.columns:
        st.warning("Coluna obsDt ausente")
        return pd.DataFrame()

    # Filtra para o período selecionado
    filtered_df = filter_data_by_date(df, start_date, end_date)

    if filtered_df.empty:
        return pd.DataFrame()

    # Extrai apenas a data (sem hora)
    if pd.api.types.is_datetime64_dtype(filtered_df['obsDt']):
        filtered_df['data'] = filtered_df['obsDt'].dt.date
    else:
        st.warning("A coluna de data não está no formato datetime")
        return pd.DataFrame()

    # Verifica qual coluna usar para espécies
    if 'speciesCode' in filtered_df.columns:
        species_col = 'speciesCode'
    elif 'commonName' in filtered_df.columns:
        species_col = 'commonName'
    else:
        # Se não houver informação de espécie, criamos tendência só de observações
        daily_obs = filtered_df.groupby('data').size().reset_index()
        daily_obs.columns = ['data', 'num_observacoes']
        daily_obs['num_especies'] = 0  # Colocamos zero como placeholder
        return daily_obs

    # Agrupa por dia e conta espécies e observações
    daily_species = filtered_df.groupby('data')[species_col].nunique().reset_index()
    daily_species.columns = ['data', 'num_especies']

    daily_obs = filtered_df.groupby('data').size().reset_index()
    daily_obs.columns = ['data', 'num_observacoes']

    # Mescla os dataframes
    daily_trend = daily_species.merge(daily_obs, on='data')

    return daily_trend


# Função para criar gráfico de tendência diária
def create_daily_trend_chart(df, title):
    """Cria um gráfico de linha para tendência diária"""
    if df.empty:
        return None

    # Cria gráfico com dois eixos Y
    fig = go.Figure()

    # Adiciona linha para espécies
    fig.add_trace(
        go.Scatter(
            x=df['data'],
            y=df['num_especies'],
            name='Espécies',
            line=dict(color='#1f77b4', width=3),
            mode='lines+markers'
        )
    )

    # Adiciona linha para observações (eixo Y secundário)
    fig.add_trace(
        go.Scatter(
            x=df['data'],
            y=df['num_observacoes'],
            name='Observações',
            line=dict(color='#ff7f0e', width=3, dash='dot'),
            mode='lines+markers',
            yaxis='y2'
        )
    )

    # Configuração do layout
    fig.update_layout(
        title=title,
        xaxis=dict(title='Data'),
        yaxis=dict(title='Nº de Espécies', side='left', showgrid=False),
        yaxis2=dict(title='Nº de Observações', side='right', overlaying='y', showgrid=False),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255, 255, 255, 0.7)'),
        margin=dict(l=10, r=10, t=50, b=10),
        height=300
    )

    return fig


# Função principal
def main():
    # Título principal
    st.title("Passarinhômetro - Avistar 2025 no Jardim Botânico de São Paulo")
    st.markdown("### Participe! Envie sua passarinhada pelo eBird e concorra a prêmios")

    # Sidebar
    # Sidebar
    with st.sidebar:
        # Definir URL fixa da planilha
        sheet_url = "https://docs.google.com/spreadsheets/d/1HCfcQXa3nqLxwsF9rok0x1NmaaHJH27TT9JfX9r4qd8/edit?usp=sharing"

        # Período de análise
        st.header("Período de Análise")

        # Determina o intervalo disponível (baseado no screenshot)
        min_date = datetime.datetime(2025, 1, 1)  # Data mais antiga observada no screenshot
        max_date = datetime.datetime(2025, 4, 13)  # Data mais recente observada no screenshot

        # Seleção de datas
        start_date = st.date_input(
            "Data inicial",
            value=min_date,
            min_value=min_date,
            max_value=max_date
        )

        end_date = st.date_input(
            "Data final",
            value=max_date,
            min_value=min_date,
            max_value=max_date
        )

        # Converte para datetime para compatibilidade
        start_datetime = datetime.datetime.combine(start_date, datetime.time.min)
        end_datetime = datetime.datetime.combine(end_date, datetime.time.max)

        # Seleção de dia específico para análises detalhadas
        available_dates = []
        current = start_date
        while current <= end_date:
            available_dates.append(current.strftime('%d/%m/%Y'))
            current += datetime.timedelta(days=1)

        selected_date = st.selectbox(
            "Dia específico para análise detalhada",
            options=available_dates,
            index=len(available_dates) - 1
        )

        # Converte a data selecionada para datetime
        selected_day = datetime.datetime.strptime(selected_date, '%d/%m/%Y')

        # Botão para atualizar dados
        if st.button("Atualizar Dados"):
            st.cache_data.clear()
            st.success("Cache limpo! Os dados serão recarregados.")

    # Carregar dados
    if sheet_url and "https://docs.google.com/spreadsheets" in sheet_url:
        with st.spinner("Carregando dados do Google Sheets..."):
            sheets_data = load_google_sheet_data(sheet_url)
    else:
        st.warning("URL da planilha inválido ou não fornecido.")
        sheets_data = {}

    # Verificar se temos dados
    if not sheets_data:
        st.error("Não foi possível carregar os dados da planilha.")
        return

    # Obter estatísticas para o período selecionado
    with st.spinner("Calculando estatísticas..."):
        # Verificar qual aba estamos usando
        event_stats = get_event_stats(sheets_data, start_datetime, end_datetime)


    # Layout principal: três colunas
    col1, col2, col3 = st.columns([1, 2, 1])

    # Coluna 1: Painel geral e métricas
    with col1:
        st.subheader("Resultados Gerais")

        # Usando métricas com bordas em vez dos gráficos gauge
        st.metric(
            label="Espécies",
            value=event_stats['especies'],
            border=True
        )

        st.metric(
            label="Listas",
            value=event_stats['listas'],
            border=True
        )

        st.metric(
            label="Passarinhantes",
            value=event_stats['observadores'],
            border=True
        )

        # Top espécies
        st.subheader(f"Top Espécies")
        top_species = get_top_species(sheets_data, start_datetime, end_datetime, limit=10)

        # Dentro da seção "Top Espécies"
        if not top_species.empty:
            st.dataframe(
                top_species,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Espécie": st.column_config.TextColumn("Espécie", width="small"),
                    "Contagem": st.column_config.ProgressColumn(
                        "Núm. de espécies",
                        format="%d",
                        min_value=0,
                        max_value=max(top_species["Contagem"]),
                        width="small"
                    )
                }
            )
        else:
            st.info("Não há dados suficientes para gerar o ranking de espécies.")

        # Top observadores
        st.subheader(f"Top Passarinhantes por Espécies")
        top_observers = get_top_observers(sheets_data, start_datetime, end_datetime, limit=10)

        # Dentro da seção "Top Observadores"
        if not top_observers.empty:
            st.dataframe(
                top_observers,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Observador": st.column_config.TextColumn("Observador", width="small"),
                    "Contagem": st.column_config.ProgressColumn(
                        "Núm. de espécies",
                        format="%d",
                        min_value=0,
                        max_value=max(top_observers["Contagem"]),
                        width="small"
                    )
                }
            )
        else:
            st.info("Não há dados suficientes para gerar o ranking de observadores.")

        # Top observadores por listas
        st.subheader(f"Top Passarinhantes por Listas")
        top_observers_lists = get_top_observers_by_lists(sheets_data, start_datetime, end_datetime, limit=10)

        # Dentro da seção "Top Observadores por Listas"
        if not top_observers_lists.empty:
            st.dataframe(
                top_observers_lists,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Observador": st.column_config.TextColumn("Observador", width="small"),
                    "Contagem": st.column_config.ProgressColumn(
                        "Listas",
                        format="%d",
                        min_value=0,
                        max_value=max(top_observers_lists["Contagem"]),
                        width="small"
                    )
                }
            )
        else:
            st.info("Não há dados suficientes para gerar o ranking de observadores por listas.")


    # Coluna 2: Dados principais e tendências
    with col2:
        # Últimas espécies
        st.subheader("Últimas Espécies Registradas")
        latest_species = get_latest_species(sheets_data, start_datetime, end_datetime, limit=100)

        if not latest_species.empty:
            # Formata para exibição
            display_species = latest_species.copy()

            # Renomeia colunas (NÃO incluir 'subId': 'ID da Lista')
            col_rename = {
                'obsDt': 'Data',
                'userDisplayName': 'Passarinhante',
                'commonName': 'Espécie'
            }

            display_species = display_species.rename(columns=col_rename)

            # Formata data
            if pd.api.types.is_datetime64_dtype(display_species['Data']):
                display_species['Data'] = display_species['Data'].dt.strftime('%d/%m/%Y %H:%M')

            # Exibe tabela
            st.dataframe(
                display_species,
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("Não há registros de espécies para o período selecionado.")

        # Últimas listas
        st.subheader("Últimas Listas Submetidas")
        latest_checklists = get_latest_checklists(sheets_data, start_datetime, end_datetime, limit=100)

        if not latest_checklists.empty:
            # Formata para exibição
            display_checklists = latest_checklists.copy()

            # Renomeia colunas
            columns_map = {
                'obsDt': 'Data',
                'subId': 'ID da Lista',
                'userDisplayName': 'Passarinhante',
                'num_especies': 'Nº Espécies'
            }

            display_checklists = display_checklists.rename(columns=columns_map)

            # Formata data
            if pd.api.types.is_datetime64_dtype(display_checklists['Data']):
                display_checklists['Data'] = display_checklists['Data'].dt.strftime('%d/%m/%Y %H:%M')

            # Exibe tabela
            st.dataframe(
                display_checklists,
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("Não há registros de listas para o período selecionado.")


        # Adicionar um divisor antes do carrossel
        st.divider()

        # SEÇÃO DO CARROSSEL DE AVES
        st.subheader("Ao vivo do mato")

        # Importar o componente
        from streamlit_carousel import carousel

        # Definir as imagens para o carrossel
        ave_slides = [
            dict(
                title="borralhara-assobiadora",
                text="Espécie registrada pelo time Emilianas",
                img="https://i.ibb.co/YFS6XV00/luciano.jpg"
            ),
            dict(
                title="formigueiro-de-cabeça-negra",
                text="O grande achado do time Emilianas",
                img="https://i.ibb.co/rKYHqCtk/luciano-0188.jpg"
            ),
            dict(
                title="surucuá-variado",
                text="Espécie registrada pelo time Penosos",
                img="https://i.ibb.co/JjBcTKzt/luciano-0278.jpg"
            )
        ]

        # Exibir o carrossel com 3 segundos de intervalo entre slides
        carousel(
            items=ave_slides,
            interval=3000,  # 3 segundos entre slides
            container_height=400,  # Altura do contêiner
            indicators=False,  # Mostrar indicadores (bolinhas)
            controls=True,  # Mostrar controles (setas)
            width=1.0,  # Largura total
            fade=True,
            wrap=True

        )

        # Adicionar um divisor após o carrossel
        st.divider()

    # Coluna 3: Rankings e análises específicas do dia
    with col3:
        # Mapa do JB-SP
        st.subheader("Hotspot")

        # Coordenadas do JB-SP
        lat_jbsp = -23.6385
        lon_jbsp = -46.6232

        # Criar mapa com Folium
        m = folium.Map(location=[lat_jbsp, lon_jbsp], zoom_start=15, tiles='OpenStreetMap')

        # Adicionar marcador para o JB-SP
        folium.Marker(
            location=[lat_jbsp, lon_jbsp],
            popup='Jardim Botânico de São Paulo',
            tooltip=folium.Tooltip('PEFI--Jardim Botânico de São Paulo', permanent=True),
            icon=folium.Icon(color='green', icon='leaf', prefix='fa')
        ).add_to(m)

        # Adicionar camada de satélite
        folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
                         attr='Google Satellite',
                         name='Google Satellite').add_to(m)

        # Adicionar controle de camadas
        folium.LayerControl().add_to(m)

        # Exibir mapa
        st_folium(m, height=300)

        # Análise do dia (movido da coluna 2 para coluna 1)
        st.subheader(f"Resultados do dia {selected_date}")

        # Converte para início e fim do dia
        day_start = datetime.datetime.combine(selected_day.date(), datetime.time.min)
        day_end = datetime.datetime.combine(selected_day.date(), datetime.time.max)

        # Obtém estatísticas do dia
        day_stats = get_event_stats(sheets_data, day_start, day_end)

        # Exibe estatísticas em métricas com bordas
        col_a, col_b, col_c = st.columns(3)

        with col_a:
            st.metric("Espécies", day_stats['especies'], border=True)

        with col_b:
            st.metric("Listas", day_stats['listas'], border=True)

        with col_c:
            st.metric("Passarinhantes", day_stats['observadores'], border=True)

        # Top Espécies do Dia (movido da coluna 2 para coluna 1)
        day_species = get_top_species(sheets_data, day_start, day_end, limit=5)

        if not day_species.empty:
            st.markdown("#### Top Espécies do Dia")

            # Exibir dataframe com barra de progresso
            st.dataframe(
                day_species,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Espécie": st.column_config.TextColumn("Espécie", width="small"),
                    "Contagem": st.column_config.ProgressColumn(
                        "Núm. de espécies",
                        format="%d",
                        min_value=0,
                        max_value=max(day_species["Contagem"]),
                        width="small"
                    )
                }
            )
        else:
            st.info(f"Não há registros de espécies para o dia {selected_date}.")

    # Rodapé
    st.markdown("---")
    st.markdown(
        """
        <div style="text-align: center; font-size: 0.8rem;">
            Passarinhômetro | by 🦉 caburé: análises de biodiversidade ágeis e inteligentes | Avistar 2025
        </div>
        """,
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
