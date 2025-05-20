import streamlit as st
import pandas as pd
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
    initial_sidebar_state="collapsed"
)

# CSS para ocultar o botão de expansão da sidebar
hide_sidebar_button = """
    <style>
        [data-testid="collapsedControl"] {
            display: none
        }
    </style>
"""
st.markdown(hide_sidebar_button, unsafe_allow_html=True)

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

# Em vez de usar st.sidebar, defina os valores diretamente no código
# Período de análise fixo
min_date = datetime.datetime(2025, 5, 16)
max_date = datetime.datetime(2025, 5, 18)
start_date = min_date
end_date = max_date

# Converte para datetime para compatibilidade
start_datetime = datetime.datetime.combine(start_date, datetime.time.min)
end_datetime = datetime.datetime.combine(end_date, datetime.time.max)

# Definir URL fixa da planilha
sheet_url = "https://docs.google.com/spreadsheets/d/1HCfcQXa3nqLxwsF9rok0x1NmaaHJH27TT9JfX9r4qd8/edit?usp=sharing"

# Carregar dados
if sheet_url and "https://docs.google.com/spreadsheets" in sheet_url:
    with st.spinner("Carregando dados do Google Sheets..."):
        sheets_data = load_google_sheet_data(sheet_url)
else:
    st.warning("URL da planilha inválido ou não fornecido.")
    sheets_data = {}

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

    # Conjunto para rastrear combinações únicas de espécie+hora (para evitar duplicatas)
    unique_species_time = set()

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

        # Para contar espécies únicas, precisamos considerar combinações de espécie+hora
        if 'speciesCode' in filtered_df.columns:
            # Iterar pelas linhas para contar espécies únicas considerando o timestamp
            for _, row in filtered_df.iterrows():
                species_code = row['speciesCode']
                obs_dt = row['obsDt']

                # Adiciona a chave espécie+hora para rastrear
                # Usamos apenas a parte de data+hora, ignorando segundos para maior robustez
                time_key = obs_dt.strftime('%Y-%m-%d %H:%M')
                species_time_key = f"{species_code}_{time_key}"

                if species_time_key not in unique_species_time:
                    unique_species_time.add(species_time_key)
                    unique_species.add(species_code)

        elif 'commonName' in filtered_df.columns:  # Usar commonName como alternativa
            # Mesma lógica para commonName
            for _, row in filtered_df.iterrows():
                common_name = row['commonName']
                obs_dt = row['obsDt']

                time_key = obs_dt.strftime('%Y-%m-%d %H:%M')
                species_time_key = f"{common_name}_{time_key}"

                if species_time_key not in unique_species_time:
                    unique_species_time.add(species_time_key)
                    unique_species.add(common_name)

        # O resto do código permanece inalterado
        # Adicionar observadores únicos - sem modificação
        if 'userDisplayName' in filtered_df.columns:
            unique_observers.update(filtered_df['userDisplayName'].unique())

        # Adicionar listas únicas - sem modificação
        if 'subId' in filtered_df.columns:
            unique_checklists.update(filtered_df['subId'].unique())

    # O restante da função permanece o mesmo...
    # (código para manipular 'observations_L2015671' e 'checklists_L2015671')

    # Preencher estatísticas
    stats['especies'] = len(unique_species)
    stats['listas'] = len(unique_checklists)
    stats['observadores'] = len(unique_observers)

    return stats

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

    # Seleciona as colunas necessárias
    cols_to_select = ['obsDt', species_col]

    # Adiciona nome científico se disponível
    if 'scientificName' in latest.columns:
        cols_to_select.append('scientificName')

    # Adiciona userDisplayName se disponível
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
# Função modificada para obter top espécies
def get_top_species(sheets_data, start_date, end_date, limit=10):
    """Obtém as espécies mais observadas no período, evitando duplicatas por horário"""
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

    # Converter obsDt para datetime se ainda não for
    if pd.api.types.is_string_dtype(filtered_df['obsDt']):
        filtered_df['obsDt'] = pd.to_datetime(filtered_df['obsDt'], errors='coerce')

    # Criar coluna de horário simplificado (sem segundos)
    if pd.api.types.is_datetime64_dtype(filtered_df['obsDt']):
        filtered_df['time_key'] = filtered_df['obsDt'].dt.strftime('%Y-%m-%d %H:%M')
    else:
        st.warning("Não foi possível processar a coluna de data para desduplicação")
        return pd.DataFrame()

    # Desduplicar registros com base na combinação espécie + horário
    # Isso preserva apenas um registro por espécie em cada horário específico
    unique_df = filtered_df.drop_duplicates(subset=[species_col, 'time_key'])

    # Conta ocorrências por espécie nos dados desduplicados
    species_counts = unique_df[species_col].value_counts().reset_index()
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

# Função para obter os primeiros registros de cada espécie
def get_first_species_records(sheets_data, start_date, end_date, limit=100):
    """Obtém o primeiro registro de cada espécie no período, ordenados por data (mais recentes primeiro)"""
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

    # Ordena por data (mais antiga primeiro)
    df_sorted = filtered_df.sort_values('obsDt')

    # Identifica o primeiro registro de cada espécie
    first_records = df_sorted.drop_duplicates(subset=[species_col], keep='first')

    # Reordena para mostrar os primeiros registros mais recentes primeiro
    first_records_sorted = first_records.sort_values('obsDt', ascending=False)

    # Seleciona as colunas necessárias
    cols_to_select = ['obsDt', species_col]

    # Adiciona nome científico se disponível
    if 'scientificName' in first_records_sorted.columns:
        cols_to_select.append('scientificName')

    # Adiciona userDisplayName se disponível
    if 'userDisplayName' in first_records_sorted.columns:
        cols_to_select.append('userDisplayName')

    result = first_records_sorted[cols_to_select].head(limit).copy()

    # Renomeia a coluna para padronizar
    if species_col != 'commonName':
        result = result.rename(columns={species_col: 'commonName'})

    return result


# Função modificada para obter todas as espécies registradas
def get_all_species(sheets_data, start_date, end_date):
    """
    Obtém todas as espécies registradas no período, com nomes populares,
    científicos e família, ordenados pelo TAXON_ORDER, removendo duplicatas de horário.
    """
    # Verificamos se temos a aba de checklists compilados
    if 'checklists_compilados' in sheets_data:
        obs_df = sheets_data['checklists_compilados']
    elif 'observations_L2015671' in sheets_data:
        obs_df = sheets_data['observations_L2015671']
    else:
        st.warning("Não foi possível encontrar dados de observações para o período.")
        return pd.DataFrame()

    # Verifica se temos as colunas necessárias
    if 'obsDt' not in obs_df.columns:
        st.warning("Coluna obsDt ausente nas observações.")
        return pd.DataFrame()

    # Filtra observações para o período selecionado
    filtered_obs = filter_data_by_date(obs_df, start_date, end_date)

    if filtered_obs.empty:
        st.warning("Não há observações para o período selecionado.")
        return pd.DataFrame()

    # Converter obsDt para datetime se ainda não for
    if pd.api.types.is_string_dtype(filtered_obs['obsDt']):
        filtered_obs['obsDt'] = pd.to_datetime(filtered_obs['obsDt'], errors='coerce')

    # Criar coluna de horário simplificado (sem segundos) para desduplicação
    if pd.api.types.is_datetime64_dtype(filtered_obs['obsDt']):
        filtered_obs['time_key'] = filtered_obs['obsDt'].dt.strftime('%Y-%m-%d %H:%M')
    else:
        st.warning("Não foi possível processar a coluna de data para desduplicação")
        return pd.DataFrame()

    # Verifica quais colunas estão disponíveis para uso
    columns_to_group = []

    # Nome comum
    species_col = None
    if 'commonName' in filtered_obs.columns:
        columns_to_group.append('commonName')
        species_col = 'commonName'
    elif 'speciesCode' in filtered_obs.columns:
        columns_to_group.append('speciesCode')
        species_col = 'speciesCode'

    # Nome científico
    if 'scientificName' in filtered_obs.columns:
        columns_to_group.append('scientificName')

    # Família
    if 'familySciName' in filtered_obs.columns:
        columns_to_group.append('familySciName')

    # TAXON_ORDER para ordenação
    has_taxon_order = 'taxonOrder' in filtered_obs.columns
    if has_taxon_order:
        columns_to_group.append('taxonOrder')

    # Se não temos colunas para agrupar, exibe um erro
    if not columns_to_group or species_col is None:
        st.warning("Não foi possível encontrar colunas para identificação de espécies.")
        return pd.DataFrame()

    # DESDUPLICAÇÃO: removemos entradas da mesma espécie com mesmo horário
    unique_obs = filtered_obs.drop_duplicates(subset=[species_col, 'time_key'])

    # Obtém espécies únicas e conta ocorrências nos dados desduplicados
    # Agrupamos pelas colunas disponíveis
    species_counts = unique_obs.groupby(columns_to_group).size().reset_index(name='Contagens')

    # Renomeia as colunas para padronização
    column_rename = {}
    if 'commonName' in columns_to_group:
        column_rename['commonName'] = 'Nome Comum'
    elif 'speciesCode' in columns_to_group:
        column_rename['speciesCode'] = 'Nome Comum'

    if 'scientificName' in columns_to_group:
        column_rename['scientificName'] = 'Nome Científico'

    if 'familySciName' in columns_to_group:
        column_rename['familySciName'] = 'Família'

    # Aplicamos a renomeação
    species_counts = species_counts.rename(columns=column_rename)

    # Ordena por TAXON_ORDER se disponível, ou alfabeticamente pelo nome comum
    if has_taxon_order:
        # Converte para numérico para garantir ordenação correta
        try:
            species_counts['taxonOrder'] = pd.to_numeric(species_counts['taxonOrder'], errors='coerce')
            species_counts = species_counts.sort_values('taxonOrder').drop(columns=['taxonOrder'])
        except:
            # Se falhar a conversão, ordena pelo nome comum
            species_counts = species_counts.sort_values('Nome Comum')
    else:
        # Ordena alfabeticamente pelo nome comum se não tiver taxonOrder
        species_counts = species_counts.sort_values('Nome Comum')

    return species_counts

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


# Função para obter histórico mensal de listas
def get_monthly_checklists_history(sheets_data, end_date, months_back=11):
    """Obtém o histórico mensal de listas submetidas nos últimos meses"""
    # Primeiro verificamos se temos a aba checklists_compilados
    if 'checklists_compilados' in sheets_data:
        df = sheets_data['checklists_compilados']
    elif 'checklists_L2015671' in sheets_data:
        df = sheets_data['checklists_L2015671']
    else:
        st.warning("Não foi possível encontrar dados para o histórico mensal.")
        return pd.DataFrame()

    # Verifica se temos as colunas necessárias
    if 'obsDt' not in df.columns or 'subId' not in df.columns:
        st.warning(f"Colunas ausentes para calcular histórico mensal")
        return pd.DataFrame()

    # Converte a coluna de data para datetime
    if pd.api.types.is_string_dtype(df['obsDt']):
        try:
            df['obsDt'] = pd.to_datetime(df['obsDt'], errors='coerce')
        except:
            st.warning("Não foi possível converter a coluna de data para datetime")
            return pd.DataFrame()

    # Calcula a data de início (months_back meses antes do final)
    end_date_dt = pd.to_datetime(end_date)
    start_date_dt = end_date_dt - pd.DateOffset(months=months_back)

    # Obtém o mês e ano de cada lista (todas as listas, sem filtrar por data)
    df_copy = df.copy()
    df_copy['month_year'] = df_copy['obsDt'].dt.to_period('M')

    # Identifica todas as listas únicas por mês
    monthly_lists = df_copy.drop_duplicates(subset=['month_year', 'subId'])

    # Conta listas únicas por mês
    monthly_counts = monthly_lists.groupby('month_year').size().reset_index(name='num_checklists')

    # Filtra para incluir apenas os meses desejados (últimos months_back + mês atual)
    start_period = pd.Period(start_date_dt, freq='M')
    end_period = pd.Period(end_date_dt, freq='M')

    monthly_counts = monthly_counts[
        (monthly_counts['month_year'] >= start_period) &
        (monthly_counts['month_year'] <= end_period)
        ]

    # Converte o período para string para melhor exibição
    monthly_counts['month_label'] = monthly_counts['month_year'].dt.strftime('%b/%Y')

    # Garante que todos os meses estejam representados, mesmo sem listas
    all_months = pd.period_range(start=start_date_dt, end=end_date_dt, freq='M')
    all_months_df = pd.DataFrame({'month_year': all_months})
    all_months_df['month_label'] = all_months_df['month_year'].dt.strftime('%b/%Y')

    # Mescla para incluir todos os meses
    complete_df = pd.merge(all_months_df, monthly_counts, on=['month_year', 'month_label'], how='left')
    complete_df['num_checklists'] = complete_df['num_checklists'].fillna(0).astype(int)

    # Ordena cronologicamente
    complete_df = complete_df.sort_values('month_year')

    return complete_df

# Função para criar gráfico de histórico mensal
def create_monthly_history_chart(df, title):
    """Cria um gráfico de linha suave para o histórico mensal de listas"""
    if df.empty:
        return None

    # Cria o gráfico com Plotly
    fig = go.Figure()

    # Adiciona a linha suave
    fig.add_trace(
        go.Scatter(
            x=df['month_label'],
            y=df['num_checklists'],
            name='Listas',  # Este nome não aparecerá, pois a legenda está desativada
            line=dict(color='#2E86C1', width=4, shape='spline'),  # Linha suave usando spline
            mode='lines+markers',
            marker=dict(size=8, color='#2874A6'),
            showlegend=False  # Remove esta série da legenda
        )
    )

    # Adiciona uma área sombreada abaixo da linha para efeito visual
    fig.add_trace(
        go.Scatter(
            x=df['month_label'],
            y=df['num_checklists'],
            name='Área',
            fill='tozeroy',
            fillcolor='rgba(46, 134, 193, 0.2)',
            line=dict(width=0),
            showlegend=False  # Remove esta série da legenda
        )
    )

    # Configuração do layout - MODIFICAÇÃO PRINCIPAL: REMOVER CORES DE FUNDO
    fig.update_layout(
        title=title,
        xaxis=dict(
            tickangle=45,
            tickfont=dict(size=10)
        ),
        yaxis=dict(
            gridcolor='rgba(230, 230, 230, 0.4)'  # Grade um pouco mais escura para tema escuro
        ),
        margin=dict(l=10, r=10, t=50, b=50),
        height=300,
        plot_bgcolor='rgba(0, 0, 0, 0)',  # Transparente - IMPORTANTE
        paper_bgcolor='rgba(0, 0, 0, 0)',  # Transparente - IMPORTANTE
        hovermode='x unified',
        showlegend=False  # Remove toda a legenda
    )

    # Destaca o mês atual (último mês) - com cor que funciona em temas escuros
    last_month_index = len(df) - 1
    if last_month_index >= 0:
        fig.add_shape(
            type="rect",
            x0=last_month_index - 0.4,
            x1=last_month_index + 0.4,
            y0=0,
            y1=df['num_checklists'].iloc[-1] * 1.1,
            fillcolor="rgba(255, 193, 7, 0.3)",  # Amarelo mais vibrante e transparência ajustada
            line=dict(width=0),
            layer="below"
        )

    return fig

# Função principal
def main():
    # Título principal
    st.title("Passarinhômetro - Avistar 2025 no Jardim Botânico de São Paulo")
    st.markdown("### Passarinhos e Passarinhantes registrados durante o evento")

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

        # SEÇÃO DO CARROSSEL DE AVES
        st.subheader("Passarinhos e Passarinhantes")

        # Importar o componente
        from streamlit_carousel import carousel

        # Definir as imagens para o carrossel
        ave_slides = [
            dict(
                title="",
                text="foto: Letícia Souza",
                img="https://i.imgur.com/lvhGWz7.jpeg"
            ),
            dict(
                title="",
                text="foto: Camila Siqueira",
                img="https://i.imgur.com/HhLNccu.jpeg"
            ),
            dict(
                title="",
                text="foto: Camila Siqueira",
                img="https://i.imgur.com/WTEQKqz.jpeg"
            ),
            dict(
                title="",
                text="foto: Camila Siqueira",
                img="https://i.imgur.com/1aPLmUu.jpeg"
            #),
            #dict(
                #title="",
                #text="foto: Camila Siqueira",
                #img="https://i.imgur.com/WTEQKqz.jpeg"
            )
        ]

        # Exibir o carrossel com 3 segundos de intervalo entre slides
        carousel(
            items=ave_slides,
            interval=2000,  # 3 segundos entre slides
            container_height=500,  # Altura do contêiner
            indicators=False,  # Mostrar indicadores (bolinhas)
            controls=True,  # Mostrar controles (setas)
            width=1.0,  # Largura total
            fade=True,
            wrap=True
        )
        # Adicionar um divisor após o carrossel
        st.divider()
        # Para "Últimas Espécies"
        st.subheader("Últimas Espécies")
        first_species = get_first_species_records(sheets_data, start_datetime, end_datetime, limit=100)

        if not first_species.empty:
            # Formata para exibição
            display_first_species = first_species.copy()

            # Renomeia colunas
            col_rename = {
                'obsDt': 'Data do Primeiro Registro',
                'userDisplayName': 'Passarinhante',
                'commonName': 'Espécie',
                'scientificName': 'Nome Científico'
            }

            display_first_species = display_first_species.rename(columns=col_rename)

            # Formata data
            if pd.api.types.is_datetime64_dtype(display_first_species['Data do Primeiro Registro']):
                display_first_species['Data do Primeiro Registro'] = display_first_species[
                    'Data do Primeiro Registro'].dt.strftime('%d/%m/%Y %H:%M')

            # Exibe tabela
            st.dataframe(
                display_first_species,
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("Não há registros de espécies para o período selecionado.")

        st.divider()

        # Para "Últimos Registros"
        st.subheader("Últimos Registros")
        latest_species = get_latest_species(sheets_data, start_datetime, end_datetime, limit=100)

        if not latest_species.empty:
            # Formata para exibição
            display_species = latest_species.copy()

            # Renomeia colunas
            col_rename = {
                'obsDt': 'Data',
                'userDisplayName': 'Passarinhante',
                'commonName': 'Espécie',
                'scientificName': 'Nome Científico'
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

        st.divider()

        # Últimas listas
        st.subheader("Últimas Listas")
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

        # Na seção onde exibimos a tabela de espécies
        st.subheader("Todas as Espécies Registradas")
        all_species = get_all_species(sheets_data, start_datetime, end_datetime)

        if not all_species.empty:
            # Configura as colunas dependendo do que está disponível no dataframe
            column_config = {
                "Nome Comum": st.column_config.TextColumn("Nome da Ave", width="medium"),
                "Contagens": st.column_config.NumberColumn("Registros", width="small")
            }

            # Adiciona configuração para Nome Científico e Família se estiverem disponíveis
            if "Nome Científico" in all_species.columns:
                column_config["Nome Científico"] = st.column_config.TextColumn(
                    "Nome Científico",
                    width="medium",
                    help="Nome científico da espécie"
                )

            if "Família" in all_species.columns:
                column_config["Família"] = st.column_config.TextColumn(
                    "Família",
                    width="medium",
                    help="Família taxonômica"
                )

            # Exibe tabela com configuração personalizada
            st.dataframe(
                all_species,
                hide_index=True,
                use_container_width=True,
                column_config=column_config
            )
        else:
            st.info("Não há registros de espécies para o período selecionado.")


    # Coluna 3: Rankings e análises específicas por dia
    with col3:
                               # Mapa do JB-SP
        st.subheader("Hotspot")
        
        # Coordenadas do JB-SP
        lat_jbsp = -23.6385
        lon_jbsp = -46.6232
        
        # Criar mapa com Folium (sem altura explícita)
        m = folium.Map(location=[lat_jbsp, lon_jbsp], zoom_start=10, tiles='OpenStreetMap')
        
        # Adicionar marcador e camadas
        folium.Marker(
            location=[lat_jbsp, lon_jbsp],
            popup='Jardim Botânico de São Paulo',
            tooltip=folium.Tooltip('PEFI--Jardim Botânico de São Paulo', permanent=True),
            icon=folium.Icon(color='green', icon='leaf', prefix='fa')
        ).add_to(m)
        
        folium.TileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
                        attr='Google Satellite',
                        name='Google Satellite').add_to(m)
        
        folium.LayerControl().add_to(m)
        
        # ABORDAGEM DIFERENTE: Remover divisor e usar CSS para controlar o mapa
        css = """
        <style>
            iframe {
                height: 500px !important;
                margin: 0 !important;
                padding: 0 !important;
            }
            div.stFolium {
                margin-bottom: 0 !important;
                padding-bottom: 0 !important;
            }
        </style>
        """
        st.markdown(css, unsafe_allow_html=True)
        
        # Exibir mapa (sem altura explícita para o mapa)
        st_folium(m)

         st.divider()
        
        # Próxima seção sem divisor nem espaçador
        st.subheader("Efeito Avistar")

        # Obtém dados históricos de 11 meses + mês atual
        monthly_history = get_monthly_checklists_history(sheets_data, end_datetime, months_back=11)

        if not monthly_history.empty:
            # Cria o gráfico
            history_chart = create_monthly_history_chart(
                monthly_history,
                "Listas Mensais Submetidas"
            )

            # Exibe o gráfico
            if history_chart:
                st.plotly_chart(history_chart, use_container_width=True)
        else:
            st.info("Não há dados históricos suficientes para gerar o gráfico.")

        st.divider()
        
        # NOVA SEÇÃO - Resultados por dia
        st.subheader("Resultados por dia")

        # Datas fixas para análise
        dias_evento = [
            datetime.datetime(2025, 5, 16),
            datetime.datetime(2025, 5, 17),
            datetime.datetime(2025, 5, 18)
        ]

        # Preparar dados para gráfico comparativo
        dias_labels = ["16/05", "17/05", "18/05"]
        especies_por_dia = []
        listas_por_dia = []
        observadores_por_dia = []

        # Coletar estatísticas para cada dia
        for dia in dias_evento:
            # Converte para início e fim do dia
            day_start = datetime.datetime.combine(dia.date(), datetime.time.min)
            day_end = datetime.datetime.combine(dia.date(), datetime.time.max)

            # Obtém estatísticas do dia
            day_stats = get_event_stats(sheets_data, day_start, day_end)

            # Armazena dados para o gráfico
            especies_por_dia.append(day_stats['especies'])
            listas_por_dia.append(day_stats['listas'])
            observadores_por_dia.append(day_stats['observadores'])

        # Criar gráfico de barras comparativo
        fig = go.Figure()

        # Adicionar barras para cada métrica
        fig.add_trace(go.Bar(
            x=dias_labels,
            y=especies_por_dia,
            name='Espécies',
            marker_color='#1f77b4'
        ))

        fig.add_trace(go.Bar(
            x=dias_labels,
            y=listas_por_dia,
            name='Listas',
            marker_color='#ff7f0e'
        ))

        fig.add_trace(go.Bar(
            x=dias_labels,
            y=observadores_por_dia,
            name='Passarinhantes',
            marker_color='#2ca02c'
        ))

        # Configurar layout sem título e sem labels nos eixos
        fig.update_layout(
            barmode='group',
            xaxis=dict(title=None),  # Remove o título do eixo X
            yaxis=dict(title=None),  # Remove o título do eixo Y
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="center",
                x=0.5
            ),
            margin=dict(l=10, r=10, t=10, b=10),  # Reduz a margem superior para eliminar espaço do título
            height=250
        )

        # Exibir gráfico
        st.plotly_chart(fig, use_container_width=True)

        # Exibir painéis para cada dia
        for i, dia in enumerate(dias_evento):
            # Formatar a data para exibição
            dia_formatado = dia.strftime('%d/%m/%Y')

            # Título do dia
            st.markdown(f"#### {dia_formatado}")

            # Converte para início e fim do dia
            day_start = datetime.datetime.combine(dia.date(), datetime.time.min)
            day_end = datetime.datetime.combine(dia.date(), datetime.time.max)

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

            # Top Espécies do Dia
            day_species = get_top_species(sheets_data, day_start, day_end, limit=5)

            if not day_species.empty:
                # Exibir dataframe com barra de progresso
                st.dataframe(
                    day_species,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Espécie": st.column_config.TextColumn("Espécie", width="small"),
                        "Contagem": st.column_config.ProgressColumn(
                            "Registros",
                            format="%d",
                            min_value=0,
                            max_value=max(day_species["Contagem"]),
                            width="small"
                        )
                    }
                )
            else:
                st.info(f"Não há registros de espécies para o dia {dia_formatado}.")

            # Adicionar divisor entre os dias
            if i < len(dias_evento) - 1:
                st.divider()

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
